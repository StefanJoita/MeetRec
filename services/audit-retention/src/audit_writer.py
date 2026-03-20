# services/audit-retention/src/audit_writer.py
# Scrie intrări în audit_logs pentru fiecare ștergere de retenție.
# Cerință legală: trebuie să existe o urmă că înregistrarea a fost ștearsă
# și de ce (politică de retenție), nu doar că a dispărut.

import uuid
from datetime import datetime, timezone

import asyncpg
import structlog

logger = structlog.get_logger(__name__)


async def log_retention_delete(
    pool: asyncpg.Pool,
    recording_id: str,
    recording_title: str,
) -> None:
    """
    Inserează un rând în audit_logs pentru ștergerea prin retenție.
    user_id = NULL (acțiunea e automată, nu a unui utilizator).
    """
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO audit_logs (id, action, resource_type, resource_id, details, success, user_ip)
            VALUES ($1, 'RETENTION_DELETE', 'recording', $2, $3, true, '127.0.0.1')
            """,
            str(uuid.uuid4()),
            recording_id,
            f'{{"title": "{recording_title}", "reason": "retention_policy"}}',
        )


async def log_audit_purge(pool: asyncpg.Pool, deleted_count: int) -> None:
    """
    Inserează un rând în audit_logs pentru purjarea log-urilor vechi.
    Paradoxal: logăm ștergerea log-urilor, dar această intrare nouă
    va fi ea însăși ștearsă după 6 ani.
    """
    if deleted_count == 0:
        return

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO audit_logs (id, action, resource_type, details, success, user_ip)
            VALUES ($1, 'RETENTION_DELETE', 'audit_logs', $2, true, '127.0.0.1')
            """,
            str(uuid.uuid4()),
            f'{{"deleted_count": {deleted_count}, "reason": "audit_log_retention_policy"}}',
        )
