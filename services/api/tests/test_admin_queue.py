# services/api/tests/test_admin_queue.py
# ============================================================
# Administrare → Coadă: listare, anulare, mutare în față
# ============================================================
# Redis = fakeredis (aceleași comenzi ca worker-ul: LPUSH / BLMOVE RIGHT).
# ============================================================

import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.config import settings
from src.main import app
from src.models.recording import RecordingStatus
from src.models.transcript import TranscriptStatus
from src.services.queue_service import (
    WORKER_STATUS_PREFIX, QueueService, cancel_key, cancel_quietly, get_queue_service,
)
from tests.test_admin_settings import login, make_user

QUEUE = settings.redis_transcription_queue
PROCESSING = f"{QUEUE}:processing:worker-a"


def job(recording_id: str, **extra) -> str:
    return json.dumps({"recording_id": recording_id, "language_hint": "ro", **extra})


async def worker_takes(redis) -> str:
    """Ce face worker-ul: BLMOVE din dreapta cozii în lista processing."""
    return await redis.lmove(QUEUE, PROCESSING, "RIGHT", "LEFT")


@pytest.fixture
def redis():
    return fakeredis.FakeAsyncRedis(decode_responses=True)


@pytest.fixture
def queue(redis):
    return QueueService(redis)


@pytest_asyncio.fixture
async def http(queue):
    app.dependency_overrides[get_queue_service] = lambda: queue
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ============================================================
# QueueService
# ============================================================

class TestQueueService:

    @pytest.mark.asyncio
    async def test_waiting_in_processing_order(self, redis, queue):
        a, b, c = (str(uuid.uuid4()) for _ in range(3))
        for rid in (a, b, c):                          # încărcate în ordinea a, b, c
            await redis.lpush(QUEUE, job(rid))

        assert [i["recording_id"] for i in await queue.waiting()] == [a, b, c]

    @pytest.mark.asyncio
    async def test_session_jobs_grouped(self, redis, queue):
        a, b = str(uuid.uuid4()), str(uuid.uuid4())
        await redis.lpush(QUEUE, job(a, segment_index=0), job(b), job(a, segment_index=1))

        assert await queue.waiting() == [{"recording_id": a, "jobs": 2}, {"recording_id": b, "jobs": 1}]

    @pytest.mark.asyncio
    async def test_running_includes_worker_progress(self, redis, queue):
        a = str(uuid.uuid4())
        await redis.lpush(QUEUE, job(a))
        await worker_takes(redis)
        await redis.set(f"{WORKER_STATUS_PREFIX}worker-a", json.dumps({
            "worker_id": "worker-a", "current_recording_id": a,
            "progress": {"transcriere": 40}, "cancelling": False}))

        [item] = await queue.running()

        assert item == {"recording_id": a, "worker_id": "worker-a", "worker_alive": True,
                        "progress": {"transcriere": 40}, "cancelling": False,
                        "cancel_requested": False}

    @pytest.mark.asyncio
    async def test_running_job_of_stopped_worker(self, redis, queue):
        a = str(uuid.uuid4())
        await redis.lpush(QUEUE, job(a))
        await worker_takes(redis)

        [item] = await queue.running()

        assert item["worker_alive"] is False and item["progress"] == {}

    @pytest.mark.asyncio
    async def test_move_to_front(self, redis, queue):
        a, b, c = (str(uuid.uuid4()) for _ in range(3))
        for rid in (a, b, c):
            await redis.lpush(QUEUE, job(rid))

        assert await queue.move_to_front(c) is True

        assert json.loads(await worker_takes(redis))["recording_id"] == c
        assert [i["recording_id"] for i in await queue.waiting()] == [a, b]

    @pytest.mark.asyncio
    async def test_move_to_front_keeps_session_job_order(self, redis, queue):
        a, b = str(uuid.uuid4()), str(uuid.uuid4())
        await redis.lpush(QUEUE, job(a, segment_index=0), job(b), job(a, segment_index=1))

        await queue.move_to_front(a)

        taken = [json.loads(await worker_takes(redis)) for _ in range(3)]
        assert [(j["recording_id"], j.get("segment_index")) for j in taken] == [(a, 0), (a, 1), (b, None)]

    @pytest.mark.asyncio
    async def test_move_to_front_missing(self, queue):
        assert await queue.move_to_front(str(uuid.uuid4())) is False

    @pytest.mark.asyncio
    async def test_cancel_waiting_removes_all_jobs(self, redis, queue):
        a, b = str(uuid.uuid4()), str(uuid.uuid4())
        await redis.lpush(QUEUE, job(a, segment_index=0), job(b), job(a, segment_index=1))

        result = await queue.cancel(a)

        assert result == {"removed": 2, "running": False}
        assert [i["recording_id"] for i in await queue.waiting()] == [b]
        # dacă worker-ul l-ar fi luat între timp, îl oprește la pornire
        assert await redis.exists(cancel_key(a))

    @pytest.mark.asyncio
    async def test_cancel_running_requests_stop(self, redis, queue):
        a = str(uuid.uuid4())
        await redis.lpush(QUEUE, job(a))
        await worker_takes(redis)

        result = await queue.cancel(a)

        assert result == {"removed": 0, "running": True}
        assert await redis.ttl(cancel_key(a)) > 0
        assert (await queue.running())[0]["cancel_requested"] is True

    @pytest.mark.asyncio
    async def test_cancel_unknown_does_nothing(self, redis, queue):
        a = str(uuid.uuid4())

        assert await queue.cancel(a) == {"removed": 0, "running": False}
        assert not await redis.exists(cancel_key(a))

    @pytest.mark.asyncio
    async def test_cancel_quietly_ignores_redis_errors(self):
        with patch("src.services.queue_service.open_redis") as open_redis:
            client = MagicMock(aclose=AsyncMock())
            client.pipeline.side_effect = ConnectionError("redis down")
            open_redis.return_value = client

            await cancel_quietly(str(uuid.uuid4()))       # nu aruncă

        client.aclose.assert_awaited_once()


# ============================================================
# API
# ============================================================

def recording_row(rid: str, title="Ședință Consiliu", status="queued"):
    return SimpleNamespace(id=uuid.UUID(rid), title=title, duration_seconds=1800,
                           status=status, created_at=datetime(2026, 10, 16, tzinfo=timezone.utc))


class TestQueueApi:

    @pytest.mark.asyncio
    async def test_list_queue_with_titles(self, http, redis):
        running, waiting, deleted = (str(uuid.uuid4()) for _ in range(3))
        for rid in (running, waiting, deleted):
            await redis.lpush(QUEUE, job(rid))
        await worker_takes(redis)
        db = login(make_user(is_admin=True))
        result = MagicMock()
        result.all.return_value = [recording_row(running, "În lucru", "transcribing"),
                                   recording_row(waiting, "Următoarea")]
        db.execute.return_value = result

        resp = await http.get("/api/v1/admin/queue")

        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] is True
        assert [(i["recording_id"], i["title"], i["status"]) for i in body["running"]] == [
            (running, "În lucru", "transcribing")]
        assert [(i["recording_id"], i["title"]) for i in body["waiting"]] == [
            (waiting, "Următoarea"), (deleted, None)]          # ștearsă: fără titlu

    @pytest.mark.asyncio
    async def test_list_queue_redis_down(self, http, queue):
        login(make_user(is_admin=True))
        queue.running = AsyncMock(side_effect=ConnectionError("redis down"))

        resp = await http.get("/api/v1/admin/queue")

        assert resp.json() == {"available": False, "running": [], "waiting": []}

    @pytest.mark.asyncio
    async def test_queue_forbidden_for_non_admin(self, http):
        login(make_user(is_admin=False))
        rid = uuid.uuid4()

        assert (await http.get("/api/v1/admin/queue")).status_code == 403
        assert (await http.post(f"/api/v1/admin/queue/{rid}/cancel")).status_code == 403
        assert (await http.post(f"/api/v1/admin/queue/{rid}/prioritize")).status_code == 403

    @pytest.mark.asyncio
    async def test_cancel_marks_recording_and_transcript_cancelled(self, http, redis):
        rid = str(uuid.uuid4())
        await redis.lpush(QUEUE, job(rid))
        db = login(make_user(is_admin=True))
        recording = MagicMock(title="Ședință", status=RecordingStatus.QUEUED.value)
        transcript = MagicMock(status=TranscriptStatus.PENDING.value)
        db.scalar.side_effect = [recording, transcript]

        with patch("src.routers.admin.log_audit", AsyncMock()) as audit:
            resp = await http.post(f"/api/v1/admin/queue/{rid}/cancel")

        assert resp.status_code == 200
        assert resp.json() == {"removed": 1, "running": False}
        assert recording.status == RecordingStatus.CANCELLED.value
        assert transcript.status == TranscriptStatus.CANCELLED.value
        assert await redis.llen(QUEUE) == 0
        assert audit.await_args.kwargs["details"] == {"resource_name": "Ședință", "event": "cancel"}
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cancel_recording_lost_from_queue(self, http):
        """Status 'queued' fără job în Redis (job pierdut): anularea îl deblochează."""
        db = login(make_user(is_admin=True))
        recording = MagicMock(title="Ședință", status=RecordingStatus.QUEUED.value)
        db.scalar.side_effect = [recording, None]

        with patch("src.routers.admin.log_audit", AsyncMock()):
            resp = await http.post(f"/api/v1/admin/queue/{uuid.uuid4()}/cancel")

        assert resp.status_code == 200
        assert recording.status == RecordingStatus.CANCELLED.value

    @pytest.mark.asyncio
    async def test_cancel_deleted_recording_still_in_queue(self, http, redis):
        rid = str(uuid.uuid4())
        await redis.lpush(QUEUE, job(rid))
        db = login(make_user(is_admin=True))
        db.scalar.return_value = None

        with patch("src.routers.admin.log_audit", AsyncMock()):
            resp = await http.post(f"/api/v1/admin/queue/{rid}/cancel")

        assert resp.status_code == 200
        assert await redis.llen(QUEUE) == 0

    @pytest.mark.asyncio
    async def test_cancel_completed_recording_conflict(self, http):
        db = login(make_user(is_admin=True))
        db.scalar.return_value = MagicMock(status=RecordingStatus.COMPLETED.value)

        resp = await http.post(f"/api/v1/admin/queue/{uuid.uuid4()}/cancel")

        assert resp.status_code == 409
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cancel_redis_down(self, http, queue):
        db = login(make_user(is_admin=True))
        db.scalar.return_value = MagicMock(status=RecordingStatus.QUEUED.value)
        queue.cancel = AsyncMock(side_effect=ConnectionError("redis down"))

        resp = await http.post(f"/api/v1/admin/queue/{uuid.uuid4()}/cancel")

        assert resp.status_code == 503
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_prioritize(self, http, redis):
        a, b = str(uuid.uuid4()), str(uuid.uuid4())
        await redis.lpush(QUEUE, job(a), job(b))
        db = login(make_user(is_admin=True))
        db.scalar.return_value = "Urgentă"

        with patch("src.routers.admin.log_audit", AsyncMock()) as audit:
            resp = await http.post(f"/api/v1/admin/queue/{b}/prioritize")

        assert resp.status_code == 200
        assert json.loads(await worker_takes(redis))["recording_id"] == b
        assert audit.await_args.kwargs["details"] == {"resource_name": "Urgentă", "event": "prioritize"}

    @pytest.mark.asyncio
    async def test_prioritize_not_waiting(self, http):
        login(make_user(is_admin=True))

        resp = await http.post(f"/api/v1/admin/queue/{uuid.uuid4()}/prioritize")

        assert resp.status_code == 409
