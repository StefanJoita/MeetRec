# services/api/src/services/audit_describe.py
# ============================================================
# Descrierea lizibilă a unei intrări din jurnalul de audit
# ============================================================
# Folosită de interfață (coloana Acțiune) și de exportul CSV, ca textul
# să fie același în ambele locuri. Numele resursei NU intră în descriere:
# are coloana lui (resource_name).
# ============================================================

import re
from typing import Any, Optional

FIELD_LABELS = {
    "title": "titlu",
    "description": "descriere",
    "meeting_date": "data ședinței",
    "location": "locație",
    "participants": "participanți",
    "classification": "nivel de clasificare",
    "email": "email",
    "full_name": "nume",
    "is_active": "activ",
    "role": "rol",
}

ROLE_LABELS = {"admin": "administrator", "operator": "operator", "participant": "participant"}

REASON_LABELS = {
    "retention_policy": "expirată (politica de retenție)",
    "abandoned_session": "sesiune fără audio, abandonată",
    "stuck_transcription": "transcriere blocată, marcată eșuată",
    "audit_log_retention_policy": "intrări vechi din jurnal șterse",
}

LOGIN_EVENTS = {
    "login_success": "autentificare reușită",
    "login_failed": "parolă greșită sau utilizator inexistent",
    "account_locked": "cont blocat după încercări eșuate",
    "login_rejected_locked": "autentificare respinsă, cont blocat",
}

# Acțiuni TRANSCRIBE: reîncercare și administrarea cozii
QUEUE_EVENTS = {
    "retry": "retrimisă la transcriere",
    "cancel": "transcriere anulată",
    "prioritize": "mutată prima în coada de transcriere",
}


def speaker_label(speaker_id: str) -> str:
    """„SPEAKER_00” → „Vorbitor 1” (aceeași etichetă ca în interfață)."""
    match = re.fullmatch(r"SPEAKER_(\d+)", speaker_id)
    return f"Vorbitor {int(match.group(1)) + 1}" if match else speaker_id


def _value(field: str, value: Any) -> str:
    if value is None or value == "" or value == []:
        return "—"
    if isinstance(value, bool):
        return "da" if value else "nu"
    if field == "role":
        return ROLE_LABELS.get(value, str(value))
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def _changes(changes: dict) -> str:
    return "; ".join(
        f"{FIELD_LABELS.get(field, field)}: {_value(field, old)} → {_value(field, new)}"
        for field, (old, new) in changes.items()
    )


def _size(size_bytes: Optional[int]) -> str:
    if not size_bytes:
        return ""
    mb = size_bytes / 1024 / 1024
    return f"{mb:.1f} MB".replace(".", ",") if mb >= 0.1 else f"{size_bytes // 1024} KB"


def _upload(d: dict) -> Optional[str]:
    event = d.get("event")
    if event == "session_completed":
        return f"sesiune finalizată ({d.get('total_segments', '?')} segmente), trimisă la transcriere"
    parts = []
    if event == "session_started":
        parts.append("sesiune de înregistrare pornită")
    if d.get("source") == "inbox_folder":
        parts.append("copiat direct în folderul inbox")
    if d.get("filename") and d.get("filename") != d.get("resource_name"):
        parts.append(d["filename"])
    if d.get("size_bytes"):
        parts.append(_size(d["size_bytes"]))
    return " · ".join(parts) or None


def describe(action: str, resource_type: Optional[str], details: Optional[dict]) -> Optional[str]:
    d = details or {}
    if action in ("SEARCH", "SEMANTIC_SEARCH") and d.get("query"):
        return f"„{d['query']}”"
    if resource_type == "app_setting" and d.get("key"):
        show = lambda v: "automat" if v is None else str(v)  # noqa: E731
        return f"{d['key']}: {show(d.get('old'))} → {show(d.get('new'))}" + (" (implicit)" if d.get("reset") else "")
    if action == "LOGIN" and d.get("event"):
        return LOGIN_EVENTS.get(d["event"], d["event"])   # utilizatorul încercat e în resource_name
    if action == "UPLOAD":
        return _upload(d)
    if d.get("event") == "password_reset":
        return "parolă resetată (schimbare obligatorie la autentificare)"
    if d.get("event") in QUEUE_EVENTS:
        return QUEUE_EVENTS[d["event"]]
    if "changes" in d:
        return _changes(d["changes"]) if d["changes"] else "fără modificări"
    if "speakers" in d:
        return "; ".join(
            f"{speaker_label(s['speaker'])}: {s['from'] or 'neatribuit'} → {s['to'] or 'neatribuit'}"
            for s in d["speakers"]
        ) or "fără modificări"
    if "participant" in d:
        return f"participant {'eliminat' if action == 'DELETE' else 'adăugat'}: {d['participant']}"
    if d.get("reason") == "audit_log_retention_policy":
        return f"{d.get('deleted_count', 0)} intrări vechi din jurnal șterse"
    if d.get("reason"):
        return REASON_LABELS.get(d["reason"], d["reason"])
    if action == "EXPORT" and d.get("format"):
        return f"format {str(d['format']).upper()}"
    if resource_type == "user" and action in ("CREATE", "DELETE") and d.get("role"):
        return f"rol {ROLE_LABELS.get(d['role'], d['role'])}"
    return None
