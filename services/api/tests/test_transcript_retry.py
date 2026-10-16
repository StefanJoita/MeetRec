# services/api/tests/test_transcript_retry.py
# ============================================================
# Teste pentru TranscriptService.retry — jobul republicat în Redis
# ============================================================
# Regresie: o sesiune multi-fișier (session_id) eșuată era republicată ca job
# standard (doar fișierul principal). Segmentele suplimentare rămâneau 'queued'
# și înregistrarea stătea în 'transcribing' la nesfârșit.
# ============================================================

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.recording import RecordingStatus
from src.models.transcript import TranscriptStatus
from src.services.transcript_service import TranscriptService


def _make_recording(session_id=None) -> MagicMock:
    recording = MagicMock()
    recording.id = uuid.uuid4()
    recording.session_id = session_id
    recording.file_path = "/data/processed/2026/10/09/abc.wav"
    recording.audio_format = "wav"
    recording.duration_seconds = 120
    recording.status = RecordingStatus.FAILED.value
    return recording


def _make_db(recording) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = recording
    db.execute.return_value = result
    return db


async def _retry_and_capture_job(recording, transcript_status=TranscriptStatus.FAILED.value) -> dict:
    service = TranscriptService(_make_db(recording))
    transcript = MagicMock(status=transcript_status)
    service.get_by_recording_id = AsyncMock(return_value=transcript)

    redis_client = AsyncMock()
    redis_cm = MagicMock()
    redis_cm.__aenter__ = AsyncMock(return_value=redis_client)
    redis_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("src.services.transcript_service.aioredis.from_url", return_value=redis_cm):
        assert await service.retry(recording.id) is True

    redis_client.lpush.assert_awaited_once()
    # o anulare veche, încă neconsumată, ar opri imediat noul job
    redis_client.delete.assert_awaited_once_with(f"transcription:cancel:{recording.id}")
    return json.loads(redis_client.lpush.await_args.args[1])


@pytest.mark.asyncio
async def test_retry_session_recording_publishes_session_job():
    recording = _make_recording(session_id=uuid.uuid4())

    job = await _retry_and_capture_job(recording)

    assert job == {
        "recording_id": str(recording.id),
        "session_mode": True,
        "language_hint": "ro",
    }
    assert recording.status == RecordingStatus.QUEUED.value


@pytest.mark.asyncio
async def test_retry_simple_upload_publishes_file_job():
    recording = _make_recording(session_id=None)

    job = await _retry_and_capture_job(recording)

    assert job["recording_id"] == str(recording.id)
    assert job["file_path"] == recording.file_path
    assert "session_mode" not in job


@pytest.mark.asyncio
async def test_retry_cancelled_recording():
    recording = _make_recording(session_id=None)
    recording.status = RecordingStatus.CANCELLED.value

    job = await _retry_and_capture_job(recording, TranscriptStatus.CANCELLED.value)

    assert job["recording_id"] == str(recording.id)
    assert recording.status == RecordingStatus.QUEUED.value


@pytest.mark.asyncio
async def test_retry_refused_while_processing():
    recording = _make_recording(session_id=None)
    service = TranscriptService(_make_db(recording))
    service.get_by_recording_id = AsyncMock(
        return_value=MagicMock(status=TranscriptStatus.PROCESSING.value))

    assert await service.retry(recording.id) is False
