# services/audit-retention/src/retention_scheduler.py
# Rulează politicile de retenție pe un interval configurat (default: zilnic).
# La startup rulează imediat, apoi așteaptă intervalul configurat.

import asyncio

import structlog

from src.config import settings
from src.database import DatabaseClient
from src.retention_policy import (
    fetch_expired_recordings,
    delete_recording,
    delete_expired_audit_logs,
)
from src.audit_writer import log_retention_delete, log_audit_purge

logger = structlog.get_logger(__name__)


class RetentionScheduler:

    def __init__(self, db: DatabaseClient):
        self._db = db
        self._running = False

    async def start(self) -> None:
        """Pornește scheduler-ul. Blochează până la stop()."""
        self._running = True
        logger.info(
            "scheduler_started",
            retention_days=settings.retention_days,
            audit_retention_days=settings.audit_log_retention_days,
            interval_seconds=settings.retention_check_interval_seconds,
        )

        while self._running:
            await self._run_once()

            if self._running:
                logger.info(
                    "scheduler_sleeping",
                    seconds=settings.retention_check_interval_seconds,
                )
                await asyncio.sleep(settings.retention_check_interval_seconds)

        logger.info("scheduler_stopped")

    def stop(self) -> None:
        """Oprește scheduler-ul după iterația curentă."""
        logger.info("scheduler_stop_requested")
        self._running = False

    async def _run_once(self) -> None:
        """O iterație completă: șterge înregistrările expirate + audit logs vechi."""
        logger.info("retention_run_started")
        pool = self._db.pool

        # ── 1. Înregistrări audio expirate ────────────────────────────────
        expired = await fetch_expired_recordings(pool)
        logger.info("expired_recordings_found", count=len(expired))

        deleted_recordings = 0
        for rec in expired:
            success = await delete_recording(pool, rec, dry_run=settings.retention_dry_run)
            if success and not settings.retention_dry_run:
                await log_retention_delete(pool, rec.id, rec.title)
                deleted_recordings += 1
            elif success and settings.retention_dry_run:
                deleted_recordings += 1  # contorizăm pentru log dry-run

        # ── 2. Audit logs vechi ────────────────────────────────────────────
        deleted_logs = await delete_expired_audit_logs(pool)
        await log_audit_purge(pool, deleted_logs)

        logger.info(
            "retention_run_completed",
            deleted_recordings=deleted_recordings,
            deleted_audit_logs=deleted_logs,
        )
