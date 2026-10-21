# services/stt-worker/src/transcriber.py
# ============================================================
# WhisperX Transcriber — transcriere + aliniere + diarizare
# ============================================================
# Pipeline față de Whisper vanilla:
#
#   1. faster-whisper (CTranslate2) — transcriere 4× mai rapidă pe CPU
#   2. wav2vec2 forced alignment   — timestamps la nivel de cuvânt
#   3. pyannote diarizare          — identificare vorbitori (opțional)
#
# Interfața publică este identică cu versiunea anterioară:
#   await transcriber.load_model()
#   segments = await transcriber.transcribe(path, language_hint)
#
# Adăugare față de versiunea anterioară:
#   TranscriptSegment.speaker_id — "SPEAKER_00", "SPEAKER_01" etc.
#   (None dacă diarization_enabled=False)
# ============================================================

import asyncio
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, List, Optional

import structlog

from src.cancellation import AnyEvent, JobCancelled, raise_if_cancelled
from src.config import settings

logger = structlog.get_logger(__name__)


def _cpu_count() -> int:
    try:
        return len(os.sched_getaffinity(0))   # respectă cpuset-ul containerului
    except AttributeError:                     # sistem fără sched_getaffinity
        return os.cpu_count() or 4


def _parallel_enabled() -> bool:
    return settings.diarization_enabled and settings.diarization_parallel


def _whisper_threads() -> int:
    """
    Fire pentru faster-whisper (fixate la încărcarea modelului): WHISPER_THREADS,
    altfel toate nucleele — sau jumătate, când diarizarea rulează în paralel.
    """
    if settings.whisper_threads > 0:
        return settings.whisper_threads
    cores = _cpu_count()
    return max(1, cores // 2) if _parallel_enabled() else cores


def _torch_threads_parallel() -> int:
    """Fire PyTorch (diarizare, aliniere) cât timp transcrierea rulează în paralel."""
    return max(1, _cpu_count() - _whisper_threads())


def _set_torch_threads(n: int) -> None:
    import torch
    torch.set_num_threads(n)


def _progress_logger(file_path: str, stage: str, step: int = 10) -> Callable[[float], None]:
    """Callback WhisperX (procent 0–100) care loghează din `step` în `step` procente."""
    next_mark = step

    def report(percent: float) -> None:
        nonlocal next_mark
        if percent >= next_mark:
            logger.info("transcription_progress", file=file_path, stage=stage,
                        percent=int(percent))
            next_mark = (int(percent) // step + 1) * step

    return report


def _stage_done(file_path: str, stage: str, started: float) -> float:
    elapsed = round(time.monotonic() - started, 1)
    logger.info("transcription_stage_done", file=file_path, stage=stage, elapsed_sec=elapsed)
    return elapsed


# ── Structura pentru un segment de transcript ────────────────

@dataclass
class TranscriptSegment:
    """
    Un segment = o unitate de vorbire cu timestamp și vorbitor.

    speaker_id: "SPEAKER_00", "SPEAKER_01" etc. dacă diarizarea e activă,
                None altfel.
    """
    segment_index: int
    start_time: float
    end_time: float
    text: str
    confidence: float
    language: str
    speaker_id: Optional[str] = None


@dataclass
class StageTimings:
    """Durata etapelor ultimei transcrieri (secunde); None = etapa nu a rulat."""
    transcription_sec: Optional[float] = None
    alignment_sec: Optional[float] = None
    diarization_sec: Optional[float] = None
    diarization_parallel: bool = False   # diarizarea s-a suprapus cu transcrierea


# ── WhisperTranscriber ────────────────────────────────────────

class WhisperTranscriber:
    """
    Încarcă modelele WhisperX și transcrie fișiere audio.

    Modele încărcate la startup (load_model):
      - faster-whisper model (transcriere, multilingv)
      - wav2vec2 alignment model pentru limba principală (timestamps cuvânt)
      - pyannote DiarizationPipeline (dacă diarization_enabled=True)

    Modelul de aliniere e specific limbii: pentru altă limbă detectată (ex. engleză)
    e încărcat la prima înregistrare în acea limbă și păstrat în memorie.
    """

    def __init__(self):
        self._model = None
        # limbă → (model, metadata) sau None (nu există / nu s-a putut încărca)
        self._align_models: dict = {}
        self._diarize_model = None
        # Procentul fiecărei etape a transcrierii în curs ({"transcriere": 42, ...}),
        # publicat de consumer în starea worker-ului (Administrare → Coadă)
        self.progress: dict = {}
        # Timpii ultimului transcribe() — worker-ul procesează un singur job odată
        self.last_timings = StageTimings()

    async def load_model(self) -> None:
        """Încarcă toate modelele necesare. Rulat o singură dată la startup."""
        logger.info("models_loading",
                    whisper_model=settings.whisper_model,
                    compute_type=settings.whisper_compute_type,
                    threads=_whisper_threads(),
                    diarization=settings.diarization_enabled)

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._load_sync)
        logger.info("models_loaded")

    def _load_sync(self) -> None:
        """Varianta sincronă — rulează în thread pool."""
        import whisperx

        # ── 1. Modelul de transcriere (faster-whisper) ────────
        # compute_type "int8": cuantizare 8-bit — cel mai rapid pe CPU
        self._model = whisperx.load_model(
            settings.whisper_model,
            device="cpu",
            compute_type=settings.whisper_compute_type,
            download_root=str(settings.whisper_model_path / "whisper"),
            language=settings.whisper_primary_language,
            threads=_whisper_threads(),
            asr_options={"no_repeat_ngram_size": settings.whisper_no_repeat_ngram_size},
        )
        logger.info("whisper_model_ready", model=settings.whisper_model,
                    no_repeat_ngram_size=settings.whisper_no_repeat_ngram_size)

        # ── 2. Modelul de aliniere (wav2vec2) — limba principală ─
        self._align_model_for(settings.whisper_primary_language)

        # ── 3. Modelul de diarizare (pyannote) ────────────────
        # Activat prin DIARIZATION_ENABLED=true în .env.
        # Modelele trebuie descărcate la build time cu HF_TOKEN.
        if settings.diarization_enabled:
            try:
                from whisperx.diarize import DiarizationPipeline
                self._diarize_model = DiarizationPipeline(
                    token=settings.hf_token or None,
                    device="cpu",
                )
                logger.info("diarization_model_ready")
            except Exception as e:
                logger.error("diarization_model_failed", error=str(e))
                self._diarize_model = None

    def _align_model_for(self, language: str) -> Optional[tuple]:
        """
        Modelul de aliniere (model, metadata) pentru limbă, încărcat la prima cerere.

        Timestamps la nivel de cuvânt (~0.1-0.3s precizie). Dacă nu e disponibil
        pentru limbă (lipsește din imagine, limbă fără model) → None, iar
        transcrierea continuă fără aliniere. Eșecul e ținut minte: nu reîncercăm
        la fiecare job.
        """
        if language not in self._align_models:
            import whisperx

            try:
                started = time.monotonic()
                self._align_models[language] = whisperx.load_align_model(
                    language_code=language,
                    device="cpu",
                )
                logger.info("align_model_ready", language=language,
                            elapsed_sec=round(time.monotonic() - started, 1))
            except Exception as e:
                logger.warning("align_model_unavailable", language=language, error=str(e))
                self._align_models[language] = None
        return self._align_models[language]

    async def transcribe(
        self,
        file_path: str,
        language_hint: Optional[str] = None,
        cancel: Optional[threading.Event] = None,
    ) -> List[TranscriptSegment]:
        """
        Transcrie un fișier audio și returnează lista de segmente.

        Dacă diarizarea e activă, fiecare segment conține speaker_id.
        `cancel` setat → JobCancelled după lotul în curs al etapei curente.
        """
        if self._model is None:
            raise RuntimeError("Model neîncărcat. Apelați load_model() înainte.")

        logger.info("transcription_started", file=file_path, language=language_hint,
                    diarization=settings.diarization_enabled)
        loop = asyncio.get_running_loop()
        start = loop.time()

        segments = await loop.run_in_executor(
            None,
            self._run_sync,
            file_path,
            language_hint,
            cancel,
        )

        elapsed = loop.time() - start
        speakers = {s.speaker_id for s in segments if s.speaker_id}
        logger.info("transcription_done", file=file_path, segments=len(segments),
                    speakers=len(speakers), elapsed_sec=round(elapsed, 1))
        return segments

    def _run_sync(
        self,
        file_path: str,
        language_hint: Optional[str],
        cancel: Optional[threading.Event] = None,
    ) -> List[TranscriptSegment]:
        """Pipeline complet: transcriere → aliniere → diarizare."""
        import whisperx

        lang = language_hint or settings.whisper_primary_language
        self.last_timings = timings = StageTimings()
        self.progress = {}
        audio = whisperx.load_audio(file_path)

        # ── 0. Diarizare în paralel (are nevoie doar de audio) ─
        minutes = len(audio) / 16000 / 60          # load_audio → 16 kHz mono
        diarize_future = None
        # Oprește firul de diarizare dacă transcrierea eșuează (rezultatul nu mai e folosit)
        stop_diarize = threading.Event()
        if self._diarize_model is not None and _parallel_enabled():
            if minutes <= settings.diarization_parallel_max_minutes:
                torch_threads = _torch_threads_parallel()
                _set_torch_threads(torch_threads)   # pentru aliniere, în firul curent
                logger.info("diarization_parallel", file=file_path, audio_minutes=round(minutes, 1),
                            whisper_threads=_whisper_threads(), torch_threads=torch_threads)
                executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="diarize")
                diarize_future = executor.submit(self._diarize, audio, file_path, torch_threads,
                                                 AnyEvent(cancel, stop_diarize))
                timings.diarization_parallel = True
                executor.shutdown(wait=False)
            else:
                logger.info("diarization_sequential_long_audio", file=file_path,
                            audio_minutes=round(minutes, 1),
                            max_minutes=settings.diarization_parallel_max_minutes)

        try:
            # ── 1. Transcriere ────────────────────────────────
            started = time.monotonic()
            # task explicit: modelul e încărcat cu limba principală, iar pentru altă limbă
            # WhisperX 3.8.6 recreează tokenizer-ul cu task-ul vechi (id de token, nu
            # "transcribe") → ValueError la orice înregistrare în altă limbă.
            result = self._model.transcribe(
                audio, batch_size=8, language=lang, task="transcribe",
                progress_callback=self._progress(file_path, "transcriere", cancel),
            )
            timings.transcription_sec = _stage_done(file_path, "transcriere", started)
            detected_language = result.get("language", lang)
            raise_if_cancelled(cancel)

            # ── 2. Aliniere forțată ───────────────────────────
            align = self._align_model_for(detected_language) if result.get("segments") else None
            if align is not None:
                align_model, align_metadata = align
                started = time.monotonic()
                try:
                    result = whisperx.align(
                        result["segments"],
                        align_model,
                        align_metadata,
                        audio,
                        device="cpu",
                        return_char_alignments=False,
                        progress_callback=self._progress(file_path, "aliniere", cancel),
                    )
                    timings.alignment_sec = _stage_done(file_path, "aliniere", started)
                except JobCancelled:
                    raise
                except Exception as e:
                    logger.warning("alignment_failed", error=str(e))
        except BaseException:
            if diarize_future is not None:
                # Firul nu poate fi oprit din afară: îi cerem să se oprească la următorul
                # pas și îl așteptăm, ca să nu concureze cu jobul următor
                logger.warning("waiting_for_parallel_diarization_after_error", file=file_path)
                stop_diarize.set()
                try:
                    diarize_future.result()
                except JobCancelled:
                    pass
                finally:
                    _set_torch_threads(_cpu_count())
            raise

        # ── 3. Diarizare (rezultatul firului paralel sau rulată acum) ─
        if diarize_future is not None:
            try:
                diarize_segments = diarize_future.result()
            finally:
                _set_torch_threads(_cpu_count())
        elif self._diarize_model is not None and result.get("segments"):
            diarize_segments = self._diarize(audio, file_path, cancel=cancel)
        else:
            diarize_segments = None

        if diarize_segments is not None and result.get("segments"):
            try:
                result = whisperx.assign_word_speakers(diarize_segments, result)
            except Exception as e:
                logger.error("diarization_failed", error=str(e))

        return [
            self._convert_segment(seg, idx, detected_language)
            for idx, seg in enumerate(result.get("segments", []))
        ]

    def _progress(self, file_path: str, stage: str,
                  cancel: Optional[threading.Event]) -> Callable[[float], None]:
        """
        Callback de progres WhisperX: loghează, reține procentul etapei și oprește
        etapa (JobCancelled) dacă jobul a fost anulat între timp.
        """
        log = _progress_logger(file_path, stage)
        self.progress[stage] = 0

        def report(percent: float) -> None:
            raise_if_cancelled(cancel)
            self.progress[stage] = int(percent)
            log(percent)

        return report

    def _diarize(self, audio, file_path: str, torch_threads: Optional[int] = None,
                 cancel: Optional[threading.Event] = None):
        """
        Diarizare pyannote. Returnează segmentele de vorbitori sau None la eroare.
        Anularea (JobCancelled) nu e o eroare de diarizare: se propagă.
        """
        if torch_threads is not None:
            _set_torch_threads(torch_threads)   # setarea PyTorch se aplică firului curent
        diarize_kwargs = {}
        if settings.min_speakers is not None:
            diarize_kwargs["min_speakers"] = settings.min_speakers
        if settings.max_speakers is not None:
            diarize_kwargs["max_speakers"] = settings.max_speakers
        started = time.monotonic()
        try:
            segments = self._diarize_model(
                audio, progress_callback=self._progress(file_path, "diarizare", cancel),
                **diarize_kwargs,
            )
        except JobCancelled:
            raise
        except Exception as e:
            logger.error("diarization_failed", error=str(e))
            return None
        self.last_timings.diarization_sec = _stage_done(file_path, "diarizare", started)
        return segments

    def _convert_segment(
        self,
        raw: dict,
        idx: int,
        detected_language: str,
    ) -> TranscriptSegment:
        """Convertește un segment WhisperX în TranscriptSegment."""
        avg_logprob = raw.get("avg_logprob")
        if avg_logprob is not None:
            confidence = round(max(0.0, min(1.0, math.exp(avg_logprob))), 3)
        else:
            words = raw.get("words", [])
            scores = [w["score"] for w in words if "score" in w]
            confidence = round(sum(scores) / len(scores), 3) if scores else 0.5

        return TranscriptSegment(
            segment_index=idx,
            start_time=float(raw.get("start", 0.0)),
            end_time=float(raw.get("end", 0.0)),
            text=raw.get("text", "").strip(),
            confidence=confidence,
            language=raw.get("language", detected_language),
            speaker_id=raw.get("speaker"),  # "SPEAKER_00" sau None
        )
