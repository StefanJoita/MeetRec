# services/api/src/services/queue_service.py
# ============================================================
# Coada de transcriere (Redis) — citire și administrare
# ============================================================
# Structura (vezi services/stt-worker/src/consumer.py):
#   <queue>                        — joburi în așteptare; producătorii fac LPUSH,
#                                    worker-ul ia din DREAPTA (BLMOVE RIGHT) →
#                                    ultimul element e următorul procesat
#   <queue>:processing:<worker_id> — jobul în lucru al fiecărui worker
#   stt_worker:status:<worker_id>  — starea publicată de worker (etapă, procent)
#   transcription:cancel:<id>      — cerere de anulare, citită de worker la ~2 s
#
# Un job e un JSON cu "recording_id"; o sesiune multi-fișier poate avea mai
# multe joburi pentru aceeași înregistrare — operațiile le tratează împreună.
#
# Modificările cozii folosesc WATCH/MULTI: dacă worker-ul ia un job între
# citire și scriere, tranzacția e reluată pe lista nouă.
# ============================================================

import json
from typing import Dict, List, Optional

import redis.asyncio as aioredis
import structlog
from redis.exceptions import WatchError

from src.config import settings

logger = structlog.get_logger(__name__)

# Identic cu services/stt-worker/src/consumer.py și src/cancellation.py
WORKER_STATUS_PREFIX = "stt_worker:status:"
CANCEL_KEY_PREFIX = "transcription:cancel:"
# Cererea de anulare expiră singură dacă niciun worker nu o consumă
CANCEL_KEY_TTL_SECONDS = 24 * 3600


def cancel_key(recording_id: str) -> str:
    return f"{CANCEL_KEY_PREFIX}{recording_id}"


def job_recording_id(raw: str) -> Optional[str]:
    try:
        value = json.loads(raw).get("recording_id")
    except (ValueError, AttributeError):
        return None
    return str(value) if value else None


class QueueService:

    def __init__(self, redis: aioredis.Redis):
        self.redis = redis
        self.queue = settings.redis_transcription_queue

    # ── Citire ───────────────────────────────────────────────

    async def waiting(self) -> List[Dict]:
        """
        Înregistrările din coadă, în ordinea procesării (următoarea prima).
        Joburile aceleiași înregistrări (sesiune multi-fișier) apar o singură dată.
        """
        raw_jobs = await self.redis.lrange(self.queue, 0, -1)
        items: Dict[str, Dict] = {}
        for raw in reversed(raw_jobs):                     # dreapta = următorul
            recording_id = job_recording_id(raw)
            if recording_id is None:
                continue
            if recording_id in items:
                items[recording_id]["jobs"] += 1
            else:
                items[recording_id] = {"recording_id": recording_id, "jobs": 1}
        return list(items.values())

    async def running(self) -> List[Dict]:
        """
        Joburile în lucru: din listele processing, completate cu starea publicată
        de worker (etapă, procent). Un job dintr-un worker oprit apare fără stare.
        """
        statuses: Dict[str, Dict] = {}
        async for key in self.redis.scan_iter(match=f"{WORKER_STATUS_PREFIX}*"):
            raw = await self.redis.get(key)
            if not raw:
                continue
            try:
                status = json.loads(raw)
            except ValueError:
                continue
            statuses[str(status.get("worker_id") or key[len(WORKER_STATUS_PREFIX):])] = status

        prefix = f"{self.queue}:processing:"
        items: Dict[str, Dict] = {}
        async for key in self.redis.scan_iter(match=f"{prefix}*"):
            worker_id = key[len(prefix):]
            status = statuses.get(worker_id) or {}
            for raw in await self.redis.lrange(key, 0, -1):
                recording_id = job_recording_id(raw)
                if recording_id is None or recording_id in items:
                    continue
                current = status.get("current_recording_id") == recording_id
                items[recording_id] = {
                    "recording_id": recording_id,
                    "worker_id": worker_id,
                    "worker_alive": bool(status),
                    "progress": (status.get("progress") or {}) if current else {},
                    "cancelling": bool(status.get("cancelling")) if current else False,
                    "cancel_requested": bool(await self.redis.exists(cancel_key(recording_id))),
                }
        return list(items.values())

    async def is_running(self, recording_id: str) -> bool:
        return any(item["recording_id"] == recording_id for item in await self.running())

    # ── Modificare ───────────────────────────────────────────

    async def remove(self, recording_id: str) -> int:
        """Scoate din coadă toate joburile înregistrării. Întoarce câte au fost scoase."""
        async with self.redis.pipeline(transaction=True) as pipe:
            while True:
                try:
                    await pipe.watch(self.queue)
                    matching = [raw for raw in await pipe.lrange(self.queue, 0, -1)
                                if job_recording_id(raw) == recording_id]
                    pipe.multi()
                    for raw in matching:
                        pipe.lrem(self.queue, 1, raw)
                    await pipe.execute()
                    return len(matching)
                except WatchError:
                    continue

    async def move_to_front(self, recording_id: str) -> bool:
        """
        Mută joburile înregistrării la capătul din care consumă worker-ul
        (următoarele procesate), păstrându-le ordinea. False dacă nu e în coadă.
        """
        async with self.redis.pipeline(transaction=True) as pipe:
            while True:
                try:
                    await pipe.watch(self.queue)
                    matching = [raw for raw in await pipe.lrange(self.queue, 0, -1)
                                if job_recording_id(raw) == recording_id]
                    if not matching:
                        await pipe.unwatch()
                        return False
                    pipe.multi()
                    for raw in matching:
                        pipe.lrem(self.queue, 1, raw)
                    # LRANGE: stânga → dreapta; RPUSH în aceeași ordine lasă cel mai
                    # vechi job (cel mai din dreapta) tot ultimul → consumat primul
                    pipe.rpush(self.queue, *matching)
                    await pipe.execute()
                    return True
                except WatchError:
                    continue

    async def request_cancel(self, recording_id: str) -> None:
        """Cere worker-ului să oprească jobul (citit la câteva secunde)."""
        await self.redis.set(cancel_key(recording_id), "1", ex=CANCEL_KEY_TTL_SECONDS)

    async def clear_cancel(self, recording_id: str) -> None:
        """La repornirea transcrierii: o cerere veche nu trebuie să oprească noul job."""
        await self.redis.delete(cancel_key(recording_id))

    async def cancel(self, recording_id: str) -> Dict[str, int | bool]:
        """
        Scoate înregistrarea din coadă și, dacă e în lucru (sau tocmai a fost
        luată de worker), cere oprirea ei.
        """
        removed = await self.remove(recording_id)
        running = await self.is_running(recording_id)
        if running or removed:
            # și după scoaterea din coadă: worker-ul poate să fi luat jobul între timp
            await self.request_cancel(recording_id)
        return {"removed": removed, "running": running}


def open_redis() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True, socket_timeout=5)


async def get_queue_service():
    """Dependency FastAPI: o conexiune Redis pe request."""
    redis = open_redis()
    try:
        yield QueueService(redis)
    finally:
        await redis.aclose()


async def cancel_quietly(recording_id: str) -> None:
    """
    Oprește transcrierea unei înregistrări șterse. Redis indisponibil nu blochează
    ștergerea: worker-ul observă oricum ștergerea din DB (verificare la 30 s).
    """
    redis = open_redis()
    try:
        await QueueService(redis).cancel(recording_id)
    except Exception as e:
        logger.warning("queue_cancel_after_delete_failed", recording_id=recording_id, error=str(e))
    finally:
        await redis.aclose()
