# services/stt-worker/src/runtime_settings.py
# ============================================================
# Setări schimbate din interfața de administrare (tabelul app_settings)
# ============================================================
# Tabelul conține doar setările suprascrise din interfață; o cheie lipsă
# înseamnă valoarea din .env (cea cu care a pornit procesul).
#
# JOB_KEYS     — aplicate înainte de fiecare job nou
# RESTART_KEYS — cer reîncărcarea modelelor: worker-ul iese între joburi,
#                Docker îl repornește (restart: unless-stopped) și la
#                pornire le citește direct din tabel
# ============================================================

import json
from typing import Any, Dict, Iterable, List

from src.config import settings

RESTART_KEYS = ("diarization_enabled", "diarization_parallel")
JOB_KEYS = ("min_speakers", "max_speakers", "max_job_attempts")
ALL_KEYS = RESTART_KEYS + JOB_KEYS

# Valorile din .env, capturate la import (înainte de orice suprascriere)
_ENV: Dict[str, Any] = {k: getattr(settings, k) for k in ALL_KEYS}
# Valorile cu care au fost încărcate modelele (setate de mark_loaded la pornire)
_loaded: Dict[str, Any] = {}

QUERY = "SELECT key, value FROM app_settings WHERE key = ANY($1::text[])"


def parse_rows(rows: Iterable[Any]) -> Dict[str, Any]:
    """Rândurile din app_settings → {cheie: valoare}. asyncpg întoarce JSONB ca text."""
    values = {}
    for row in rows:
        raw = row["value"]
        values[row["key"]] = json.loads(raw) if isinstance(raw, str) else raw
    return values


def apply(values: Dict[str, Any], keys: Iterable[str]) -> Dict[str, Any]:
    """Aplică pe `settings` valorile din tabel (sau din .env, pentru cheile lipsă). Întoarce ce s-a schimbat."""
    changed = {}
    for key in keys:
        new = values.get(key, _ENV[key])
        if getattr(settings, key) != new:
            setattr(settings, key, new)
            changed[key] = new
    return changed


def mark_loaded() -> None:
    """Reține valorile cu care au fost încărcate modelele."""
    _loaded.clear()
    _loaded.update({k: getattr(settings, k) for k in RESTART_KEYS})


def restart_needed(values: Dict[str, Any]) -> List[str]:
    """Cheile RESTART_KEYS care diferă de cele cu care s-au încărcat modelele."""
    return [k for k in RESTART_KEYS if values.get(k, _ENV[k]) != _loaded.get(k, _ENV[k])]
