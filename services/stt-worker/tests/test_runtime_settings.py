# services/stt-worker/tests/test_runtime_settings.py
# ============================================================
# Setările din Administrare → Setări (tabelul app_settings) în stt-worker
# ============================================================

import json
from unittest.mock import AsyncMock, MagicMock

import asyncpg
import fakeredis
import pytest

from src import runtime_settings
from src.config import settings
from src.consumer import STATUS_PREFIX, STATUS_TTL_SECONDS, JobConsumer
from src.uploader import DatabaseUploader


@pytest.fixture(autouse=True)
def restore_settings():
    saved = {k: getattr(settings, k) for k in runtime_settings.ALL_KEYS}
    loaded = dict(runtime_settings._loaded)
    yield
    for k, v in saved.items():
        setattr(settings, k, v)
    runtime_settings._loaded.clear()
    runtime_settings._loaded.update(loaded)


def make_consumer(values):
    uploader = AsyncMock()
    uploader.fetch_app_settings = AsyncMock(return_value=values)
    consumer = JobConsumer(transcriber=AsyncMock(progress={}), uploader=uploader,
                           detector=AsyncMock(), postprocessor=MagicMock())
    consumer._exit_process = MagicMock()
    consumer._redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    return consumer


class TestApply:

    def test_table_values_override_env(self):
        changed = runtime_settings.apply({"max_job_attempts": 4, "min_speakers": 2},
                                         runtime_settings.JOB_KEYS)

        assert settings.max_job_attempts == 4 and settings.min_speakers == 2
        assert changed == {"max_job_attempts": 4, "min_speakers": 2}

    def test_missing_key_returns_to_env_value(self):
        env = runtime_settings._ENV["max_job_attempts"]
        runtime_settings.apply({"max_job_attempts": env + 1}, runtime_settings.JOB_KEYS)

        changed = runtime_settings.apply({}, runtime_settings.JOB_KEYS)   # resetat din interfață

        assert settings.max_job_attempts == env
        assert changed == {"max_job_attempts": env}

    def test_parse_rows_decodes_jsonb_text(self):
        rows = [{"key": "min_speakers", "value": "null"}, {"key": "diarization_enabled", "value": "true"}]

        assert runtime_settings.parse_rows(rows) == {"min_speakers": None, "diarization_enabled": True}


class TestRestartNeeded:

    def test_changed_restart_key_detected(self):
        runtime_settings.mark_loaded()
        flipped = not settings.diarization_enabled

        assert runtime_settings.restart_needed({"diarization_enabled": flipped}) == ["diarization_enabled"]

    def test_same_values_need_no_restart(self):
        runtime_settings.mark_loaded()
        same = {k: getattr(settings, k) for k in runtime_settings.RESTART_KEYS}

        assert runtime_settings.restart_needed(same) == []
        assert runtime_settings.restart_needed({}) == []    # nimic în tabel = valorile din .env


class TestConsumerRefresh:

    async def test_job_settings_applied_between_jobs(self):
        runtime_settings.mark_loaded()
        consumer = make_consumer({"max_speakers": 3})

        await consumer._refresh_settings()

        assert settings.max_speakers == 3
        consumer._exit_process.assert_not_called()

    async def test_diarization_change_restarts_worker(self):
        runtime_settings.mark_loaded()
        consumer = make_consumer({"diarization_enabled": not settings.diarization_enabled})

        await consumer._refresh_settings()

        consumer._exit_process.assert_called_once()

    async def test_db_error_keeps_current_settings(self):
        runtime_settings.mark_loaded()
        consumer = make_consumer({})
        consumer._uploader.fetch_app_settings.side_effect = ConnectionError("db down")
        before = settings.max_job_attempts

        await consumer._refresh_settings()

        assert settings.max_job_attempts == before
        consumer._exit_process.assert_not_called()


class TestWorkerStatus:

    async def test_status_published_with_ttl(self):
        consumer = make_consumer({})

        await consumer._publish_status("rec-1")

        key = f"{STATUS_PREFIX}{consumer._worker_id}"
        status = json.loads(await consumer._redis.get(key))
        assert status["current_recording_id"] == "rec-1"
        assert status["whisper_model"] == settings.whisper_model
        assert 0 < await consumer._redis.ttl(key) <= STATUS_TTL_SECONDS

    async def test_status_includes_stage_progress(self):
        consumer = make_consumer({})
        consumer._transcriber.progress = {"transcriere": 100, "aliniere": 40}

        await consumer._publish_status("rec-1")
        busy = json.loads(await consumer._redis.get(f"{STATUS_PREFIX}{consumer._worker_id}"))
        await consumer._publish_status()
        idle = json.loads(await consumer._redis.get(f"{STATUS_PREFIX}{consumer._worker_id}"))

        assert busy["progress"] == {"transcriere": 100, "aliniere": 40}
        assert busy["cancelling"] is False
        assert idle["progress"] == {}

    async def test_redis_error_is_not_fatal(self):
        consumer = make_consumer({})
        consumer._redis = MagicMock()
        consumer._redis.set = AsyncMock(side_effect=ConnectionError("redis down"))

        await consumer._publish_status()      # nu aruncă


class TestUploaderFetch:

    async def test_missing_table_returns_empty(self):
        conn = AsyncMock()
        conn.fetch.side_effect = asyncpg.UndefinedTableError("app_settings")
        acq = AsyncMock()
        acq.__aenter__.return_value = conn
        uploader = DatabaseUploader()
        uploader._pool = MagicMock(acquire=MagicMock(return_value=acq))

        assert await uploader.fetch_app_settings() == {}
