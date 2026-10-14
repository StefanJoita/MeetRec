# services/api/src/services/app_settings.py
# ============================================================
# Setări de funcționare schimbate din interfața de administrare
# ============================================================
# Sursa adevărului pentru ce se poate schimba din interfață. Valoarea
# efectivă a unei setări:
#   1. rândul din tabelul app_settings, dacă există (setat din interfață)
#   2. altfel variabila de mediu (.env), transmisă containerului
#   3. altfel valoarea implicită din cod
#
# Serviciile care folosesc setările (stt-worker, audit-retention, ingest)
# citesc ele însele tabelul app_settings; API-ul doar îl scrie și îl afișează.
#
# Nu sunt aici, intenționat: secretele (parole, JWT), căile, rețeaua, versiunea,
# modelul Whisper (fiecare imagine stt-worker conține un singur model, ales de
# docker-compose din .env) și limba (doar modelul de aliniere pentru română e inclus).
# ============================================================

import os
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.app_setting import AppSetting

MIB = 1024 * 1024
NGINX_MAX_UPLOAD_MB = 600   # client_max_body_size din nginx: o limită mai mare n-ar avea efect


@dataclass(frozen=True)
class SettingDef:
    key: str
    env: str
    type: str                     # "int" | "bool" | "optional_int"
    default: Any
    group: str
    label: str
    description: str
    applies: str                  # când intră în vigoare, afișat în interfață
    min: Optional[int] = None
    max: Optional[int] = None
    unit: Optional[str] = None
    from_env: Optional[Callable[[str], Any]] = None   # conversie specială din variabila de mediu


_NEXT_JOB = "La următoarea transcriere."
_WORKER_RESTART = ("Worker-ul de transcriere se repornește automat când nu are nimic "
                   "în lucru (încărcarea modelelor durează 1-3 minute).")
_NEXT_CHECK = "La următoarea verificare (cel mult 15 minute)."
_NEXT_RETENTION = "La următoarea rulare a politicii de retenție (zilnic)."

SETTINGS: List[SettingDef] = [
    SettingDef(
        "diarization_enabled", "DIARIZATION_ENABLED", "bool", False, "Transcriere",
        "Identificarea vorbitorilor (diarizare)",
        "Separă vorbitorii în transcriere (Vorbitor 1, Vorbitor 2...). Necesită modelul "
        "de diarizare în pachet. Mărește durata procesării.",
        _WORKER_RESTART,
    ),
    SettingDef(
        "diarization_parallel", "DIARIZATION_PARALLEL", "bool", True, "Transcriere",
        "Diarizare în paralel cu transcrierea",
        "Rulează diarizarea în același timp cu transcrierea, pe jumătate din nuclee fiecare. "
        "Dezactivat: etapele rulează una după alta.",
        _WORKER_RESTART,
    ),
    SettingDef(
        "min_speakers", "MIN_SPEAKERS", "optional_int", None, "Transcriere",
        "Număr minim de vorbitori",
        "Ajută diarizarea când știți dinainte câți vorbitori sunt. Gol = detectare automată.",
        _NEXT_JOB, min=1, max=20,
    ),
    SettingDef(
        "max_speakers", "MAX_SPEAKERS", "optional_int", None, "Transcriere",
        "Număr maxim de vorbitori",
        "Limitează numărul de vorbitori detectați. Gol = detectare automată.",
        _NEXT_JOB, min=1, max=20,
    ),
    SettingDef(
        "max_job_attempts", "MAX_JOB_ATTEMPTS", "int", 2, "Joburi",
        "Încercări pe același fișier",
        "De câte ori poate cădea worker-ul pe același fișier (ex. memorie insuficientă) "
        "înainte ca înregistrarea să fie marcată „Eșuat”.",
        _NEXT_JOB, min=1, max=5,
    ),
    SettingDef(
        "stuck_transcription_hours", "STUCK_TRANSCRIPTION_HOURS", "int", 6, "Joburi",
        "Transcriere blocată după",
        "O înregistrare „În transcriere” de mai mult de atât, fără job în coadă, e marcată "
        "„Eșuat” și poate fi reluată cu „Reîncearcă”.",
        _NEXT_CHECK, min=1, max=72, unit="ore",
    ),
    SettingDef(
        "abandoned_session_hours", "ABANDONED_SESSION_HOURS", "int", 24, "Joburi",
        "Ștergere sesiuni fără audio după",
        "Sesiunile pre-înregistrate de un client care n-au primit niciun fișier audio valid "
        "sunt șterse după acest interval.",
        _NEXT_CHECK, min=1, max=720, unit="ore",
    ),
    SettingDef(
        "max_file_size_mb", "MAX_FILE_SIZE_BYTES", "int", 500, "Încărcare",
        "Mărimea maximă a unui fișier",
        f"Fișierele mai mari sunt refuzate la încărcare. Maxim {NGINX_MAX_UPLOAD_MB} MB "
        "(limita serverului web).",
        "Imediat.", min=1, max=NGINX_MAX_UPLOAD_MB, unit="MB",
        from_env=lambda raw: max(1, int(raw) // MIB),
    ),
    SettingDef(
        "retention_days", "RETENTION_DAYS", "int", 1095, "Retenție",
        "Păstrarea înregistrărilor",
        "Înregistrările (audio și transcriere) mai vechi de atât sunt șterse automat. "
        "Minimum 30 de zile, ca o greșeală de tastare să nu șteargă tot.",
        _NEXT_RETENTION, min=30, max=3650, unit="zile",
    ),
    SettingDef(
        "audit_log_retention_days", "AUDIT_LOG_RETENTION_DAYS", "int", 2190, "Retenție",
        "Păstrarea jurnalului de audit",
        "Intrările din jurnalul de audit mai vechi de atât sunt șterse automat. Minimum un an.",
        _NEXT_RETENTION, min=365, max=3650, unit="zile",
    ),
]

BY_KEY: Dict[str, SettingDef] = {s.key: s for s in SETTINGS}


class SettingValidationError(ValueError):
    pass


def env_value(d: SettingDef) -> Any:
    """Valoarea din .env (variabila de mediu a containerului API), altfel cea implicită."""
    raw = os.environ.get(d.env, "").split("#", 1)[0].strip()
    if raw == "":
        return d.default
    try:
        if d.from_env:
            return d.from_env(raw)
        if d.type == "bool":
            return raw.lower() in ("1", "true", "yes", "da", "on")
        return int(raw)
    except ValueError:
        return d.default


def validate(d: SettingDef, value: Any) -> Any:
    """Verifică tipul și limitele; întoarce valoarea normalizată."""
    if d.type == "bool":
        if not isinstance(value, bool):
            raise SettingValidationError("Valoarea trebuie să fie adevărat sau fals.")
        return value
    if value is None:
        if d.type == "optional_int":
            return None
        raise SettingValidationError("Valoarea este obligatorie.")
    if isinstance(value, bool) or not isinstance(value, int):
        raise SettingValidationError("Valoarea trebuie să fie un număr întreg.")
    if d.min is not None and value < d.min:
        raise SettingValidationError(f"Valoarea minimă este {d.min}.")
    if d.max is not None and value > d.max:
        raise SettingValidationError(f"Valoarea maximă este {d.max}.")
    return value


async def overrides(db: AsyncSession) -> Dict[str, AppSetting]:
    rows = (await db.execute(select(AppSetting))).scalars().all()
    return {r.key: r for r in rows if r.key in BY_KEY}


def effective(d: SettingDef, overridden: Dict[str, AppSetting]) -> Any:
    row = overridden.get(d.key)
    return row.value if row is not None else env_value(d)


async def effective_value(db: AsyncSession, key: str) -> Any:
    d = BY_KEY[key]
    row = await db.get(AppSetting, key)
    return row.value if row is not None else env_value(d)


def check_consistency(values: Dict[str, Any]) -> None:
    """Reguli între setări (după aplicarea modificării)."""
    lo, hi = values.get("min_speakers"), values.get("max_speakers")
    if lo is not None and hi is not None and lo > hi:
        raise SettingValidationError("Numărul minim de vorbitori nu poate depăși numărul maxim.")


async def set_value(db: AsyncSession, key: str, value: Any, user_id: Optional[uuid.UUID]) -> Any:
    d = BY_KEY[key]
    value = validate(d, value)
    current = await overrides(db)
    values = {s.key: effective(s, current) for s in SETTINGS}
    values[key] = value
    check_consistency(values)
    stmt = insert(AppSetting).values(key=key, value=value, updated_by=user_id)
    stmt = stmt.on_conflict_do_update(
        index_elements=[AppSetting.key],
        set_={"value": stmt.excluded.value, "updated_by": user_id, "updated_at": func.now()},
    )
    await db.execute(stmt)
    return value


async def reset_value(db: AsyncSession, key: str) -> None:
    current = await overrides(db)
    values = {s.key: effective(s, current) for s in SETTINGS}
    values[key] = env_value(BY_KEY[key])
    check_consistency(values)
    await db.execute(delete(AppSetting).where(AppSetting.key == key))
