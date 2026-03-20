# services/audit-retention/src/retention_policy.py
# Implementează politicile de ștergere conform regulilor de retenție.
#
# Reguli:
#   - Înregistrări audio: șterse după RETENTION_DAYS (default 3 ani)
#     Condiție: recordings.retain_until < NOW()
#     Efect: șterge fișierul de pe disc + rândul din DB (CASCADE șterge transcript)
#
#   - Audit logs: șterse după AUDIT_LOG_RETENTION_DAYS (default 6 ani)
#     Condiție: audit_logs.timestamp < NOW() - interval
#     Efect: DELETE din DB (nu au fișiere asociate)

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import List

import asyncpg
import structlog

from src.config import settings

logger = structlog.get_logger(__name__)


@dataclass
class RecordingToDelete:
    id: str
    title: str
    file_path: str
    retain_until: date


async def fetch_expired_recordings(pool: asyncpg.Pool) -> List[RecordingToDelete]:
    """
    Returnează înregistrările cu retain_until expirat.
    retain_until NULL înseamnă că nu are politică de ștergere → ignorăm.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, file_path, retain_until
            FROM recordings
            WHERE retain_until IS NOT NULL
              AND retain_until < CURRENT_DATE
              AND status != 'archived'
            ORDER BY retain_until ASC
            """
        )
    return [
        RecordingToDelete(
            id=str(row["id"]),
            title=row["title"],
            file_path=row["file_path"],
            retain_until=row["retain_until"],
        )
        for row in rows
    ]


async def delete_recording(pool: asyncpg.Pool, rec: RecordingToDelete) -> bool:
    """
    Șterge o înregistrare expirată:
    1. Fișierul audio de pe disc
    2. Rândul din DB (CASCADE șterge transcript + segmente)

    Returnează True dacă ștergerea a reușit.
    """
    # Pas 1: ștergem fișierul fizic
    file_path = Path(rec.file_path)
    if file_path.exists():
        try:
            file_path.unlink()
            logger.info("audio_file_deleted", path=str(file_path), recording_id=rec.id)
        except OSError as e:
            logger.error("audio_file_delete_failed", path=str(file_path), error=str(e))
            return False
    else:
        logger.warning("audio_file_not_found", path=str(file_path), recording_id=rec.id)

    # Pas 2: ștergem rândul din DB
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM recordings WHERE id = $1",
            rec.id,
        )

    logger.info(
        "recording_deleted",
        recording_id=rec.id,
        title=rec.title,
        retain_until=str(rec.retain_until),
    )
    return True


async def delete_expired_audit_logs(pool: asyncpg.Pool) -> int:
    """
    Șterge audit logs mai vechi decât AUDIT_LOG_RETENTION_DAYS.
    Returnează numărul de rânduri șterse.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.audit_log_retention_days)

    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM audit_logs WHERE timestamp < $1",
            cutoff,
        )

    # asyncpg returnează "DELETE N" — extragem numărul
    deleted_count = int(result.split()[-1])
    if deleted_count > 0:
        logger.info(
            "audit_logs_deleted",
            count=deleted_count,
            older_than=cutoff.isoformat(),
        )
    return deleted_count
