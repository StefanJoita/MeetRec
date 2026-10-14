# services/audit-retention/tests/test_stuck_reaper.py
# ============================================================
# Teste pentru reaper-ul transcrierilor blocate
# ============================================================
# Redis: fakeredis (coada principală + liste processing reale).
# DB: un pool minim în memorie — candidații din SELECT și statusul fiecărei
# înregistrări, ca UPDATE ... WHERE status = 'transcribing' să se comporte real.
# ============================================================

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import fakeredis
import pytest

from src.stuck_reaper import (
    STUCK_MESSAGE,
    StuckTranscriptionReaper,
    reap_abandoned_sessions,
    reap_stuck_transcriptions,
    recording_ids_in_redis,
)

QUEUE = "transcription_jobs"
HOURS = 6


class FakeConn:
    def __init__(self, db):
        self.db = db

    async def fetch(self, sql, *args):
        if "FROM app_settings" in sql:
            return [{"key": k, "value": json.dumps(v)} for k, v in self.db.app_settings.items()]
        if "DELETE FROM recordings" in sql:
            # sesiunile „vechi” fără audio (SQL-ul real filtrează după ore și file_path)
            self.db.delete_args.append(args)
            assert "status = 'session_registered'" in sql and "file_path = ''" in sql
            deleted = [{"id": rid, "title": title} for rid, title in self.db.sessions.items()]
            self.db.sessions.clear()
            return deleted
        self.db.select_args.append(args)
        return [{"id": rid} for rid, status in self.db.recordings.items() if status == "transcribing"]

    async def fetchval(self, sql, recording_id, message):
        assert "status = 'transcribing'" in sql
        if self.db.recordings.get(recording_id) != "transcribing":
            return None
        self.db.recordings[recording_id] = "failed"
        self.db.messages[recording_id] = message
        return recording_id

    async def execute(self, sql, *args):
        if "INSERT INTO audit_logs" in sql:
            self.db.audit.append(json.loads(args[2]))
        elif "UPDATE transcripts" in sql:
            self.db.failed_transcripts.append(args[0])

    def transaction(self):
        tx = AsyncMock()
        tx.__aenter__ = AsyncMock(return_value=None)
        tx.__aexit__ = AsyncMock(return_value=False)
        return tx


class FakeDB:
    """Înregistrările „vechi” în 'transcribing' (SELECT-ul real filtrează după ore)."""

    def __init__(self, recordings: dict, sessions: dict | None = None):
        self.recordings = dict(recordings)
        self.sessions = dict(sessions or {})   # id → titlu, sesiuni abandonate
        self.delete_args: list = []
        self.app_settings: dict = {}           # Administrare → Setări
        self.messages: dict = {}
        self.failed_transcripts: list = []
        self.audit: list = []
        self.select_args: list = []

    @property
    def pool(self):
        acq = AsyncMock()
        acq.__aenter__ = AsyncMock(return_value=FakeConn(self))
        acq.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=acq)
        return pool


def job(recording_id: str, **extra) -> str:
    return json.dumps({"recording_id": recording_id, **extra})


@pytest.fixture
def redis():
    return fakeredis.FakeAsyncRedis(decode_responses=True)


class TestReapStuckTranscriptions:

    @pytest.mark.asyncio
    async def test_stuck_recording_without_job_is_marked_failed(self, redis):
        lost = str(uuid.uuid4())
        db = FakeDB({lost: "transcribing"})

        reaped = await reap_stuck_transcriptions(db.pool, redis, QUEUE, HOURS)

        assert reaped == 1
        assert db.recordings[lost] == "failed"
        assert db.messages[lost] == STUCK_MESSAGE.format(hours=HOURS)
        assert db.failed_transcripts == [lost]
        assert db.audit == [{"reason": "stuck_transcription", "stuck_hours": HOURS}]

    @pytest.mark.asyncio
    async def test_recording_still_in_main_queue_is_not_touched(self, redis):
        waiting = str(uuid.uuid4())
        await redis.lpush(QUEUE, job(waiting))
        db = FakeDB({waiting: "transcribing"})

        assert await reap_stuck_transcriptions(db.pool, redis, QUEUE, HOURS) == 0
        assert db.recordings[waiting] == "transcribing"

    @pytest.mark.asyncio
    async def test_recording_in_any_processing_list_is_not_touched(self, redis):
        running = str(uuid.uuid4())
        await redis.lpush(f"{QUEUE}:processing:stt-worker-2", job(running, attempts=1))
        db = FakeDB({running: "transcribing"})

        assert await reap_stuck_transcriptions(db.pool, redis, QUEUE, HOURS) == 0
        assert db.recordings[running] == "transcribing"

    @pytest.mark.asyncio
    async def test_only_lost_recordings_are_reaped(self, redis):
        lost, running = str(uuid.uuid4()), str(uuid.uuid4())
        await redis.lpush(f"{QUEUE}:processing:stt-worker-1", job(running))
        db = FakeDB({lost: "transcribing", running: "transcribing"})

        assert await reap_stuck_transcriptions(db.pool, redis, QUEUE, HOURS) == 1
        assert db.recordings == {lost: "failed", running: "transcribing"}

    @pytest.mark.asyncio
    async def test_threshold_hours_passed_to_query(self, redis):
        db = FakeDB({})

        await reap_stuck_transcriptions(db.pool, redis, QUEUE, 12)

        assert db.select_args == [(12,)]

    @pytest.mark.asyncio
    async def test_no_candidates_does_not_read_redis(self):
        broken_redis = MagicMock()
        broken_redis.scan_iter = MagicMock(side_effect=AssertionError("Redis nu trebuia citit"))

        assert await reap_stuck_transcriptions(FakeDB({}).pool, broken_redis, QUEUE, HOURS) == 0

    @pytest.mark.asyncio
    async def test_redis_error_marks_nothing(self):
        lost = str(uuid.uuid4())
        db = FakeDB({lost: "transcribing"})
        reaper = StuckTranscriptionReaper(db)
        broken_redis = MagicMock()
        broken_redis.scan_iter = MagicMock(side_effect=ConnectionError("Redis down"))
        reaper._redis = broken_redis

        await reaper._run_once()                # nu aruncă excepție

        assert db.recordings[lost] == "transcribing"


class TestReapAbandonedSessions:

    @pytest.mark.asyncio
    async def test_abandoned_sessions_are_deleted_and_audited(self):
        sid = str(uuid.uuid4())
        db = FakeDB({}, sessions={sid: "Ședința CA"})

        assert await reap_abandoned_sessions(db.pool, 24) == 1

        assert db.sessions == {}
        assert db.delete_args == [(24,)]
        assert db.audit == [{"reason": "abandoned_session", "title": "Ședința CA", "abandoned_hours": 24}]

    @pytest.mark.asyncio
    async def test_nothing_to_delete(self):
        db = FakeDB({})

        assert await reap_abandoned_sessions(db.pool, 24) == 0
        assert db.audit == []

    @pytest.mark.asyncio
    async def test_run_once_cleans_sessions_even_if_redis_is_down(self):
        sid = str(uuid.uuid4())
        db = FakeDB({str(uuid.uuid4()): "transcribing"}, sessions={sid: "x"})
        reaper = StuckTranscriptionReaper(db)
        broken_redis = MagicMock()
        broken_redis.scan_iter = MagicMock(side_effect=ConnectionError("Redis down"))
        reaper._redis = broken_redis

        await reaper._run_once()

        assert db.sessions == {}


class TestRunOnceUsesAppSettings:

    @pytest.mark.asyncio
    async def test_hours_from_admin_settings_are_used(self, monkeypatch):
        from src import runtime_settings
        from src.config import settings
        for k in runtime_settings.KEYS:
            monkeypatch.setattr(settings, k, getattr(settings, k))   # restaurat după test
        db = FakeDB({}, sessions={str(uuid.uuid4()): "x"})
        db.app_settings = {"abandoned_session_hours": 48, "stuck_transcription_hours": 3}
        reaper = StuckTranscriptionReaper(db)
        reaper._redis = fakeredis.FakeAsyncRedis(decode_responses=True)

        await reaper._run_once()

        assert settings.stuck_transcription_hours == 3
        assert db.delete_args == [(48,)]


class TestRecordingIdsInRedis:

    @pytest.mark.asyncio
    async def test_reads_main_queue_and_all_processing_lists(self, redis):
        await redis.lpush(QUEUE, job("a"), job("b"))
        await redis.lpush(f"{QUEUE}:processing:w1", job("c"))
        await redis.lpush(f"{QUEUE}:processing:w2", job("d", interrupted=True))
        await redis.lpush("alta_coada", job("e"))

        assert await recording_ids_in_redis(redis, QUEUE) == {"a", "b", "c", "d"}

    @pytest.mark.asyncio
    async def test_ignores_invalid_entries(self, redis):
        await redis.lpush(QUEUE, "NOT JSON", json.dumps(["listă"]), json.dumps({"fara": "id"}), job("ok"))

        assert await recording_ids_in_redis(redis, QUEUE) == {"ok"}
