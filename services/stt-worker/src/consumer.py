# services/stt-worker/src/consumer.py
# ============================================================
# Job Consumer — consumă joburi de transcriere din Redis
# ============================================================
# Patternul BRPOP (Blocking Right POP):
#
#   INGEST: LPUSH queue job_json  ← adaugă la stânga (head)
#   WORKER: BRPOP queue timeout   ← extrage din dreapta (tail)
#
#   Vizualizare coadă FIFO:
#   [job_nou, job_recent, job_vechi_1, job_vechi_2]
#   ↑ LPUSH adaugă aici          ↑ BRPOP extrage de aici
#
#   BRPOP cu timeout=30:
#   - Dacă coada e goală: BLOCHEAZĂ 30 secunde, returnează None
#   - Dacă apare un job: returnează (queue_name, job_json) IMEDIAT
#   - Nu consumă CPU cât așteaptă (Redis notifică clientul)
#
# IMPORTANT: Folosim redis.asyncio (nu redis.Redis sync)!
# redis.Redis.brpop() blochează THREAD-UL PYTHON pe 30 de secunde.
# Într-un program asyncio, asta blochează ÎNTREGUL EVENT LOOP.
# redis.asyncio.Redis.brpop() face await — event loop-ul rămâne liber.
# ============================================================

import asyncio
import json
import time
from typing import Optional

import redis.asyncio as aioredis
import structlog

from src.audio_assembler import AudioAssembler, AssemblyError
from src.config import settings
from src.language_detector import LanguageDetector
from src.postprocessor import PostProcessor
from src.transcriber import WhisperTranscriber, TranscriptSegment
from src.uploader import DatabaseUploader, TranscriptMetadata

logger = structlog.get_logger(__name__)


class JobConsumer:
    """
    Consumă joburi de transcriere din Redis și orchestrează pipeline-ul.

    Pipeline per job:
        job din Redis
            ↓ parse JSON
            ↓ mark_processing (DB)
            ↓ detect language (Whisper, 30s audio)
            ↓ transcribe (Whisper, întreg fișierul)
            ↓ postprocess (diacritice, spații)
            ↓ save_results (DB: segmente + metadata)
    """

    def __init__(
        self,
        transcriber: WhisperTranscriber,
        uploader: DatabaseUploader,
        detector: LanguageDetector,
        postprocessor: PostProcessor,
        assembler: Optional[AudioAssembler] = None,
    ):
        self._transcriber = transcriber
        self._uploader = uploader
        self._detector = detector
        self._postprocessor = postprocessor
        self._assembler = assembler or AudioAssembler()
        self._redis: Optional[aioredis.Redis] = None
        self._running = False
        self._queue = settings.redis_transcription_queue

    # ── Lifecycle ─────────────────────────────────────────────

    async def start(self) -> None:
        """
        Pornește loop-ul de consum. Blochează până la stop().

        Creăm conexiunea Redis AICI (nu în constructor) pentru că:
        - settings sunt deja validate
        - suntem sigur că suntem în contextul asyncio corect
        """
        self._redis = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_timeout=35,  # ușor mai mult decât BRPOP timeout (30s)
        )
        self._running = True
        logger.info("consumer_started", queue=self._queue)

        while self._running:
            await self._poll_once()

        # Cleanup
        await self._redis.aclose()
        logger.info("consumer_stopped")

    def stop(self) -> None:
        """
        Semnalează oprirea loop-ului.
        Loop-ul se oprește după cel mult 30 de secunde (timeout-ul BRPOP).
        Nu întrerupe o transcriere în curs — aceasta se termină.

        Apelat din signal handler (SIGTERM) în main.py.
        """
        logger.info("consumer_stop_requested")
        self._running = False

    # ── Poll ──────────────────────────────────────────────────

    async def _poll_once(self) -> None:
        """
        O iterație a loop-ului: încearcă să ia un job din Redis.

        BRPOP returnează:
        - None dacă timeout-ul expiră fără niciun job → iterăm
        - (queue_name, job_json) dacă vine un job → procesăm

        timeout=30: verificăm _running la fiecare 30 secunde.
        Compromis: oprire în max 30s vs. verificare mai frecventă (CPU waste).
        """
        try:
            result = await self._redis.brpop(self._queue, timeout=30)
        except Exception as e:
            # Redis temporar indisponibil (restart, network blip)
            # Așteptăm 5s și reîncercăm — nu vrem să spamăm logurile
            logger.warning("redis_brpop_error", error=str(e))
            await asyncio.sleep(5)
            return

        if result is None:
            # Timeout normal — coada e goală
            return

        _queue_name, job_json = result

        try:
            job = json.loads(job_json)
        except json.JSONDecodeError as e:
            logger.error("invalid_job_json", error=str(e), raw=job_json[:200])
            return  # mesajul corupt e pierdut (nu îl putem reprocesa)

        await self._process_job(job)

    # ── Process job ───────────────────────────────────────────

    async def _process_job(self, job: dict) -> None:
        """
        Rutare job: session_mode → _process_session_job, altfel pipeline standard.

        Job standard (upload simplu fără session_id):
        {
            "recording_id": "uuid",
            "file_path": "/data/processed/...",
            "audio_format": "mp3",
            "duration_seconds": 3600,
            "language_hint": "ro",
        }

        Job sesiune (publicat de Session Watcher după timeout):
        {
            "recording_id": "uuid",
            "session_mode": true,
            "language_hint": "ro",
        }
        """
        if job.get("session_mode"):
            await self._process_session_job(job)
            return
        recording_id = job.get("recording_id")
        file_path = job.get("file_path")
        language_hint = job.get("language_hint", settings.whisper_primary_language)
        # Prezente doar pentru segmente suplimentare (fișier 2, 3, ... dintr-o sesiune)
        segment_id: Optional[str] = job.get("segment_id")
        audio_segment_index: Optional[int] = job.get("segment_index")

        logger.info(
            "job_started",
            recording_id=recording_id,
            file=file_path,
            segment_index=audio_segment_index,
        )
        job_start = time.monotonic()

        # ── Pasul 1: Obținem transcript_id din DB ─────────────
        # Ingest-ul a creat deja rândul din transcripts cu status='pending'
        transcript_id = await self._uploader.get_transcript_id(recording_id)
        if not transcript_id:
            logger.error("transcript_missing", recording_id=recording_id)
            return  # nu putem continua fără transcript_id

        try:
            # ── Pasul 2: Marcăm ca 'processing' ───────────────
            model_name = f"whisper-{settings.whisper_model}"
            await self._uploader.mark_processing(transcript_id, recording_id, model_name)

            # ── Pasul 3: Detectăm limba ────────────────────────
            # Rulează pe primele 30s ale audio-ului (rapid, ~2-5s)
            # Dacă detectarea eșuează, detector.detect() returnează language_hint
            detected_language = await self._detector.detect(file_path)

            # Dacă language_hint e "ro" dar audio e clar altceva, override-uim
            final_language = detected_language or language_hint
            if final_language != language_hint:
                logger.warning(
                    "language_override",
                    hint=language_hint,
                    detected=detected_language,
                )

            # ── Pasul 4: Transcriem ────────────────────────────
            # Pasul lent: 10 minute pentru 1 oră de audio pe CPU
            segments = await self._transcriber.transcribe(file_path, final_language)

            # ── Pasul 5: Post-procesăm ─────────────────────────
            # Diacritice + whitespace — rapid, sincron
            segments = self._postprocessor.process(segments)

            # ── Pasul 6: Calculăm metadata agregată ───────────
            processing_time = int(time.monotonic() - job_start)
            metadata = self._compute_metadata(segments, final_language, model_name, processing_time)

            # ── Gardă: 0 segmente = Whisper nu a detectat vorbire ─
            if not segments:
                logger.warning(
                    "no_speech_detected",
                    recording_id=recording_id,
                    file=file_path,
                    model=model_name,
                    hint="Consider a higher-quality recording or a larger Whisper model.",
                )

            # ── Pasul 7: Calculăm offset-urile pentru sesiuni multi-part ──
            # Fiecare fișier suplimentar (segment_index > 0) are nevoie de:
            #   - index_offset: evită conflictele pe (transcript_id, segment_index)
            #     Whisper numerotează segmentele de la 0 pentru fiecare fișier.
            #     Dacă fișierul 1 are segmente 0..47, fișierul 2 trebuie să înceapă de la 48.
            #   - time_offset_sec: face timestamps-urile continue în transcript
            #     Fișierul 2 începe de la 0.0s relativ la el, dar în transcript
            #     trebuie să înceapă de la durata totală a fișierelor anterioare.
            if audio_segment_index and audio_segment_index > 0:
                index_offset = await self._uploader.get_transcript_index_offset(transcript_id)
                time_offset_sec = await self._uploader.get_time_offset_seconds(
                    recording_id, audio_segment_index
                )
            else:
                index_offset = 0
                time_offset_sec = 0.0

            # ── Pasul 8: Salvăm în DB ──────────────────────────
            await self._uploader.save_results(
                transcript_id=transcript_id,
                recording_id=recording_id,
                segments=segments,
                metadata=metadata,
                index_offset=index_offset,
                time_offset_sec=time_offset_sec,
                segment_id=segment_id,
            )

            logger.info(
                "job_completed",
                recording_id=recording_id,
                segments=len(segments),
                words=metadata.word_count,
                processing_sec=processing_time,
                segment_index=audio_segment_index,
            )

        except Exception as e:
            # Orice eroare → marcăm ca failed și continuăm cu alt job
            # Workerul NU se oprește! Un job eșuat nu trebuie să oprească tot serviciul.
            logger.error("job_failed", recording_id=recording_id, error=str(e), exc_info=True)
            await self._uploader.mark_failed(transcript_id, recording_id, str(e))

    async def _process_session_job(self, job: dict) -> None:
        """
        Pipeline pentru sesiuni multi-segment (audio concatenat).

        Diferențe față de _process_job standard:
        - Nu are file_path în job → interogăm DB pentru toate segmentele
        - Concatenăm toate fișierele audio în ordinea segment_index
        - Transcriem fișierul concatenat o singură dată → fără artefacte la joncțiuni
        - Salvăm cu save_session_results (marchează direct completed, fără pending_count)
        - Ștergem fișierul temporar concatenat în finally
        """
        recording_id = job.get("recording_id")
        language_hint = job.get("language_hint", settings.whisper_primary_language)

        logger.info("session_job_started", recording_id=recording_id)
        job_start = time.monotonic()

        transcript_id = await self._uploader.get_transcript_id(recording_id)
        if transcript_id is None:
            logger.error("session_transcript_not_found", recording_id=recording_id)
            return

        model_name = f"whisper-{settings.whisper_model}"
        await self._uploader.mark_processing(transcript_id, recording_id, model_name)

        merged_path = None
        try:
            # ── 1. Obținem toate căile audio sortate după segment_index ─
            paths = await self._uploader.get_all_session_segments(recording_id)
            if not paths:
                raise ValueError(f"Nicio cale audio găsită pentru recording {recording_id}")

            # ── 2. Detectăm limba pe primul segment (~30s audio) ────────
            detected_language = await self._detector.detect(str(paths[0]))

            # ── 3. Concatenăm toate segmentele într-un singur fișier WAV ─
            merged_path = await self._assembler.assemble(paths)

            # ── 4. Transcriem audio-ul concatenat o singură dată ────────
            segments = await self._transcriber.transcribe(
                str(merged_path), detected_language
            )
            segments = self._postprocessor.process(segments)

            processing_time = int(time.monotonic() - job_start)
            metadata = self._compute_metadata(
                segments, detected_language, model_name, processing_time
            )

            # ── 5. Salvăm în DB ─────────────────────────────────────────
            await self._uploader.save_session_results(
                transcript_id=transcript_id,
                recording_id=recording_id,
                segments=segments,
                metadata=metadata,
            )

            logger.info(
                "session_job_completed",
                recording_id=recording_id,
                segments=len(segments),
                words=metadata.word_count,
                processing_sec=processing_time,
            )

        except (AssemblyError, Exception) as e:
            logger.error("session_job_failed", recording_id=recording_id, error=str(e), exc_info=True)
            await self._uploader.mark_failed(transcript_id, recording_id, str(e))

        finally:
            # Ștergem fișierul temporar concatenat indiferent de rezultat
            if merged_path is not None and merged_path.exists():
                merged_path.unlink(missing_ok=True)

    def _compute_metadata(
        self,
        segments: list,
        language: str,
        model_name: str,
        processing_time_sec: int,
    ) -> TranscriptMetadata:
        """
        Calculează metadatele agregate din lista de segmente.

        word_count: numărul de cuvinte din toate segmentele
        confidence_avg: media scorurilor de confidence (medie aritmetică simplă)
        """
        if not segments:
            return TranscriptMetadata(
                word_count=0,
                confidence_avg=0.0,
                processing_time_sec=processing_time_sec,
                language=language,
                model_used=model_name,
            )

        total_words = sum(len(seg.text.split()) for seg in segments)
        avg_confidence = sum(seg.confidence for seg in segments) / len(segments)

        return TranscriptMetadata(
            word_count=total_words,
            confidence_avg=round(avg_confidence, 3),
            processing_time_sec=processing_time_sec,
            language=language,
            model_used=model_name,
        )
