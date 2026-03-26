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
from dataclasses import dataclass
from typing import List, Optional

import structlog

from src.config import settings

logger = structlog.get_logger(__name__)


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


# ── WhisperTranscriber ────────────────────────────────────────

class WhisperTranscriber:
    """
    Încarcă modelele WhisperX și transcrie fișiere audio.

    Modele încărcate la startup (load_model):
      - faster-whisper model (transcriere)
      - wav2vec2 alignment model (timestamps cuvânt)
      - pyannote DiarizationPipeline (dacă diarization_enabled=True)
    """

    def __init__(self):
        self._model = None
        self._align_model = None
        self._align_metadata = None
        self._diarize_model = None

    async def load_model(self) -> None:
        """Încarcă toate modelele necesare. Rulat o singură dată la startup."""
        logger.info("models_loading",
                    whisper_model=settings.whisper_model,
                    compute_type=settings.whisper_compute_type,
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
        )
        logger.info("whisper_model_ready", model=settings.whisper_model)

        # ── 2. Modelul de aliniere (wav2vec2) ─────────────────
        # Timestamps la nivel de cuvânt (~0.1-0.3s precizie).
        # Dacă nu e disponibil pentru limbă → continuăm fără.
        try:
            self._align_model, self._align_metadata = whisperx.load_align_model(
                language_code=settings.whisper_primary_language,
                device="cpu",
            )
            logger.info("align_model_ready", language=settings.whisper_primary_language)
        except Exception as e:
            logger.warning("align_model_unavailable", error=str(e))
            self._align_model = None
            self._align_metadata = None

        # ── 3. Modelul de diarizare (pyannote) ────────────────
        # Activat prin DIARIZATION_ENABLED=true în .env.
        # Modelele trebuie descărcate la build time cu HF_TOKEN.
        if settings.diarization_enabled:
            try:
                self._diarize_model = whisperx.DiarizationPipeline(
                    use_auth_token=settings.hf_token or None,
                    device="cpu",
                )
                logger.info("diarization_model_ready")
            except Exception as e:
                logger.error("diarization_model_failed", error=str(e))
                self._diarize_model = None

    async def transcribe(
        self,
        file_path: str,
        language_hint: Optional[str] = None,
    ) -> List[TranscriptSegment]:
        """
        Transcrie un fișier audio și returnează lista de segmente.

        Dacă diarizarea e activă, fiecare segment conține speaker_id.
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
    ) -> List[TranscriptSegment]:
        """Pipeline complet: transcriere → aliniere → diarizare."""
        import whisperx

        lang = language_hint or settings.whisper_primary_language
        audio = whisperx.load_audio(file_path)

        # ── 1. Transcriere ────────────────────────────────────
        result = self._model.transcribe(audio, batch_size=8, language=lang)
        detected_language = result.get("language", lang)

        # ── 2. Aliniere forțată ───────────────────────────────
        if self._align_model is not None and result.get("segments"):
            try:
                result = whisperx.align(
                    result["segments"],
                    self._align_model,
                    self._align_metadata,
                    audio,
                    device="cpu",
                    return_char_alignments=False,
                )
            except Exception as e:
                logger.warning("alignment_failed", error=str(e))

        # ── 3. Diarizare ──────────────────────────────────────
        if self._diarize_model is not None and result.get("segments"):
            try:
                diarize_kwargs = {}
                if settings.min_speakers is not None:
                    diarize_kwargs["min_speakers"] = settings.min_speakers
                if settings.max_speakers is not None:
                    diarize_kwargs["max_speakers"] = settings.max_speakers

                diarize_segments = self._diarize_model(audio, **diarize_kwargs)
                result = whisperx.assign_word_speakers(diarize_segments, result)
            except Exception as e:
                logger.error("diarization_failed", error=str(e))

        return [
            self._convert_segment(seg, idx, detected_language)
            for idx, seg in enumerate(result.get("segments", []))
        ]

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
