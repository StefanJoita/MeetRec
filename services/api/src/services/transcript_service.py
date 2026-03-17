# services/api/src/services/transcript_service.py
# ============================================================
# Transcript Service — Business logic pentru transcrieri
# ============================================================

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.transcript import Transcript, TranscriptStatus
from src.models.recording import Recording, RecordingStatus


class TranscriptService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_recording_id(self, recording_id: uuid.UUID) -> Optional[Transcript]:
        """
        Returnează transcriptul complet (cu segmente) pentru o înregistrare.
        Segmentele sunt încărcate automat (lazy='selectin' în model).
        """
        result = await self.db.execute(
            select(Transcript).where(Transcript.recording_id == recording_id)
        )
        return result.scalar_one_or_none()

    async def retry(self, recording_id: uuid.UUID) -> bool:
        """
        Retrimite un job de transcriere eșuat în Redis.
        Condiție: înregistrarea există și transcriptul are status 'failed'.

        Returns:
            True dacă jobul a fost retrimes, False altfel.
        """
        # Verificăm că înregistrarea există
        rec_result = await self.db.execute(
            select(Recording).where(Recording.id == recording_id)
        )
        recording = rec_result.scalar_one_or_none()
        if not recording:
            return False

        # Verificăm că transcriptul e în stare 'failed'
        transcript = await self.get_by_recording_id(recording_id)
        if not transcript or transcript.status != TranscriptStatus.FAILED.value:
            return False

        # Resetăm statusurile
        transcript.status = TranscriptStatus.PENDING.value
        transcript.error_message = None
        recording.status = RecordingStatus.QUEUED.value
        await self.db.flush()

        # Republicăm jobul în Redis
        await self._publish_job(recording)
        return True

    async def _publish_job(self, recording: Recording) -> None:
        """Publică job de transcriere în Redis."""
        import json
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        job = {
            "recording_id": str(recording.id),
            "file_path": recording.file_path,
            "audio_format": recording.audio_format,
            "duration_seconds": recording.duration_seconds or 0,
            "language_hint": "ro",
        }
        await r.lpush(settings.redis_transcription_queue, json.dumps(job))
        await r.aclose()
