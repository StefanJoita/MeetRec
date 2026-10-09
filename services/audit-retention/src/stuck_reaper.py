# services/audit-retention/src/stuck_reaper.py
# Plasă de siguranță pentru transcrierile blocate în 'transcribing'.
#
# stt-worker folosește o coadă fiabilă (lista "<coadă>:processing:<worker_id>"),
# deci un job nu se mai pierde când procesul moare. Rămân însă cazuri în care
# o înregistrare stă în 'transcribing' fără niciun job în Redis:
#   - joburi pierdute înainte de coada fiabilă (BRPOP)
#   - eroare neprevăzută la marcarea 'failed' (ex. DB indisponibil)
#   - Redis golit / restaurat
#
# La fiecare STUCK_CHECK_INTERVAL_SECONDS: înregistrările aflate în
# 'transcribing' de peste STUCK_TRANSCRIPTION_HOURS care NU apar nici în coada
# principală, nici în vreo listă processing sunt marcate 'failed'. Utilizatorul
# le poate relua cu butonul „Reîncearcă”.

import asyncio
import json
from typing import List, Set

import asyncpg
import redis.asyncio as aioredis
import structlog

from src.audit_writer import log_stuck_transcription_failed
from src.config import settings
from src.database import DatabaseClient

logger = structlog.get_logger(__name__)

STUCK_MESSAGE = (
    "Transcrierea nu s-a finalizat în {hours} ore și jobul nu mai există în coada "
    "de procesare. Folosiți „Reîncearcă”."
)


async def fetch_stuck_recordings(pool: asyncpg.Pool, hours: int) -> List[str]:
    """Înregistrările în 'transcribing' de peste `hours` ore (de la ultima pornire a jobului)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT r.id
            FROM recordings r
            LEFT JOIN transcripts t ON t.recording_id = r.id
            WHERE r.status = 'transcribing'
              AND COALESCE(t.started_at, r.updated_at) < NOW() - make_interval(hours => $1)
            """,
            hours,
        )
    return [str(row["id"]) for row in rows]


async def recording_ids_in_redis(redis: aioredis.Redis, queue: str) -> Set[str]:
    """
    recording_id-urile din coada principală și din toate listele processing.

    Listele sunt citite într-o singură tranzacție (MULTI): un job mutat între
    coadă și processing (BLMOVE / recuperare la pornire) apare exact o dată.
    """
    processing_keys = [key async for key in redis.scan_iter(match=f"{queue}:processing:*")]
    async with redis.pipeline(transaction=True) as pipe:
        for key in [queue, *processing_keys]:
            pipe.lrange(key, 0, -1)
        lists = await pipe.execute()

    ids: Set[str] = set()
    for raw in (raw for items in lists for raw in items):
        try:
            recording_id = json.loads(raw).get("recording_id")
        except (ValueError, AttributeError):
            continue
        if recording_id:
            ids.add(str(recording_id))
    return ids


async def mark_stuck_failed(pool: asyncpg.Pool, recording_id: str, message: str) -> bool:
    """Marchează 'failed' doar dacă înregistrarea e încă în 'transcribing'."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            updated = await conn.fetchval(
                """
                UPDATE recordings
                SET status = 'failed', error_message = $2, updated_at = NOW()
                WHERE id = $1 AND status = 'transcribing'
                RETURNING id
                """,
                recording_id,
                message,
            )
            if updated is None:
                return False
            await conn.execute(
                """
                UPDATE transcripts
                SET status = 'failed', error_message = $2, completed_at = NOW()
                WHERE recording_id = $1 AND status <> 'completed'
                """,
                recording_id,
                message,
            )
    return True


async def reap_stuck_transcriptions(
    pool: asyncpg.Pool,
    redis: aioredis.Redis,
    queue: str,
    hours: int,
) -> int:
    """O trecere completă. Returnează câte înregistrări au fost marcate 'failed'."""
    candidates = await fetch_stuck_recordings(pool, hours)
    if not candidates:
        return 0

    # Erorile Redis se propagă: fără imaginea cozii nu putem ști ce e pierdut
    in_redis = await recording_ids_in_redis(redis, queue)
    message = STUCK_MESSAGE.format(hours=hours)

    reaped = 0
    for recording_id in candidates:
        if recording_id in in_redis:
            # Încă în coadă sau în lucru (ex. transcriere foarte lungă) — nu e pierdut
            logger.info("stuck_recording_still_queued", recording_id=recording_id)
            continue
        if await mark_stuck_failed(pool, recording_id, message):
            await log_stuck_transcription_failed(pool, recording_id, hours)
            logger.warning("stuck_transcription_marked_failed", recording_id=recording_id, hours=hours)
            reaped += 1
    return reaped


class StuckTranscriptionReaper:

    def __init__(self, db: DatabaseClient):
        self._db = db
        self._running = False
        self._stop_event = asyncio.Event()
        self._redis: aioredis.Redis | None = None

    async def start(self) -> None:
        """Rulează periodic. Blochează până la stop()."""
        self._running = True
        self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        logger.info(
            "stuck_reaper_started",
            stuck_hours=settings.stuck_transcription_hours,
            interval_seconds=settings.stuck_check_interval_seconds,
        )
        try:
            while self._running:
                await self._run_once()
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=settings.stuck_check_interval_seconds,
                    )
                except asyncio.TimeoutError:
                    pass
        finally:
            await self._redis.aclose()
            logger.info("stuck_reaper_stopped")

    def stop(self) -> None:
        self._running = False
        self._stop_event.set()

    async def _run_once(self) -> None:
        try:
            reaped = await reap_stuck_transcriptions(
                self._db.pool,
                self._redis,
                settings.redis_transcription_queue,
                settings.stuck_transcription_hours,
            )
        except Exception as e:
            # Redis/DB indisponibil: nu marcăm nimic, reîncercăm la următoarea trecere
            logger.error("stuck_reaper_error", error=str(e))
            return
        if reaped:
            logger.warning("stuck_reaper_run_completed", reaped=reaped)
