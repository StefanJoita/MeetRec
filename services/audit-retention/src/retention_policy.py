# services/audit-retention/src/retention_policy.py
# Implementează politicile de ștergere conform regulilor de retenție.
#
# Reguli:
#   - Înregistrări audio: șterse după RETENTION_DAYS (default 3 ani)
#     Condiție: retain_until (dacă e setat explicit), altfel created_at + RETENTION_DAYS,
#     a trecut. RETENTION_DAYS poate fi schimbat din Administrare → Setări.
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
    Returnează înregistrările expirate: retain_until, dacă e setat explicit,
    altfel data creării + RETENTION_DAYS. (retain_until nu e completat la
    creare, deci fără valoarea calculată nicio înregistrare n-ar expira.)
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, file_path, expires AS retain_until
            FROM (
                SELECT id, title, file_path, status,
                       COALESCE(retain_until, (created_at + make_interval(days => $1))::date) AS expires
                FROM recordings
            ) r
            WHERE expires < CURRENT_DATE
              AND status != 'archived'
            ORDER BY expires ASC
            """,
            settings.retention_days,
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


async def delete_recording(
    pool: asyncpg.Pool,
    rec: RecordingToDelete,
    dry_run: bool = False,
) -> bool:
    """
    Șterge o înregistrare expirată.
    Ordinea: DB PRIMUL, filesystem după — pentru atomicitate.

    Dacă dry_run=True, logăm ce ar fi șters fără să ștergem nimic.
    Returnează True dacă ștergerea a reușit (sau în dry-run).
    """
    if dry_run:
        logger.info(
            "dry_run_would_delete",
            recording_id=rec.id,
            title=rec.title,
            file_path=rec.file_path,
            retain_until=str(rec.retain_until),
        )
        return True

    file_path = Path(rec.file_path) if rec.file_path else None

    # Pas 1: ștergem din DB PRIMUL
    # Dacă DB eșuează, fișierul rămâne intact (nicio pierdere de date)
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM recordings WHERE id = $1",
            rec.id,
        )
        if result == "DELETE 0":
            logger.warning("recording_already_deleted", recording_id=rec.id)
            return False

    # Pas 2: ștergem fișierul DUPĂ ce DB-ul a confirmat
    # Dacă unlink() eșuează, logăm dar NU facem rollback DB
    if file_path and file_path.exists():
        try:
            file_path.unlink()
            logger.info("audio_file_deleted", path=str(file_path), recording_id=rec.id)
        except OSError as e:
            logger.error(
                "orphaned_file_after_retention_delete",
                path=str(file_path),
                recording_id=rec.id,
                error=str(e),
            )
    else:
        logger.warning("audio_file_not_found", path=str(rec.file_path), recording_id=rec.id)

    logger.info(
        "recording_deleted",
        recording_id=rec.id,
        title=rec.title,
        retain_until=str(rec.retain_until),
    )
    return True


# Trigger-ul audit_logs_protect din baza de date refuză ștergerea intrărilor mai noi de atât
AUDIT_LOG_MIN_RETENTION_DAYS = 365


async def delete_expired_audit_logs(pool: asyncpg.Pool) -> int:
    """
    Șterge audit logs mai vechi decât AUDIT_LOG_RETENTION_DAYS (minimum un an).
    Returnează numărul de rânduri șterse.
    """
    days = max(settings.audit_log_retention_days, AUDIT_LOG_MIN_RETENTION_DAYS)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

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
