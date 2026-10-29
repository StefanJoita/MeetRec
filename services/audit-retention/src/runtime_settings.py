# services/audit-retention/src/runtime_settings.py
# ============================================================
# Setări schimbate din interfața de administrare (tabelul app_settings)
# ============================================================
# Tabelul conține doar setările suprascrise din interfață; o cheie lipsă
# înseamnă valoarea din .env. Aplicate la începutul fiecărei treceri
# (retenție zilnică, reaper la 15 minute).
# ============================================================

import json
from typing import Any, Dict

import asyncpg
import structlog

from src.config import settings

logger = structlog.get_logger(__name__)

KEYS = (
    "retention_days",
    "audit_log_retention_days",
    "stuck_transcription_hours",
    "abandoned_session_hours",
    "backup_enabled",
    "backup_hour",
    "backup_keep_daily",
    "backup_keep_weekly",
    "backup_deleted_audio_days",
)

# Valorile din .env, capturate la import (înainte de orice suprascriere)
_ENV: Dict[str, Any] = {k: getattr(settings, k) for k in KEYS}


async def refresh(pool: asyncpg.Pool) -> Dict[str, Any]:
    """Citește app_settings și aplică pe `settings`. DB indisponibil → valorile curente rămân."""
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT key, value FROM app_settings WHERE key = ANY($1::text[])", list(KEYS)
            )
    except asyncpg.UndefinedTableError:
        rows = []                       # API-ul n-a aplicat încă migrarea 010
    except Exception as e:
        logger.warning("app_settings_refresh_failed", error=str(e))
        return {}

    values = {}
    for row in rows:
        raw = row["value"]
        values[row["key"]] = json.loads(raw) if isinstance(raw, str) else raw

    changed = {}
    for key in KEYS:
        new = values.get(key, _ENV[key])
        if getattr(settings, key) != new:
            setattr(settings, key, new)
            changed[key] = new
    if changed:
        logger.info("app_settings_applied", **changed)
    return changed
