# services/api/src/routers/inbox.py
# ============================================================
# Router /inbox — Poarta de intrare pentru fișiere audio
# ============================================================
# Arhitectura corectă:
#   Browser → POST /inbox/upload → API salvează în /data/inbox/
#   Ingest Service detectează (inotify) → validează → DB → Redis
#
# API-ul nu validează fișierul audio — asta e responsabilitatea
# Ingest Service-ului care are AudioValidator complet.
# ============================================================

import json
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File, status
from pydantic import BaseModel

from src.config import settings
from src.middleware.auth import get_current_user

router = APIRouter(
    prefix="/inbox",
    tags=["inbox"],
    dependencies=[Depends(get_current_user)],
)


class InboxUploadResponse(BaseModel):
    """Răspuns simplu: am primit fișierul, aștepți procesarea."""
    message: str
    filename: str


@router.post(
    "/upload",
    response_model=InboxUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trimite fișier audio la transcriere",
    description=(
        "Salvează fișierul în inbox-ul monitorizat de Ingest Service. "
        "Câmpurile de metadate (title, meeting_date, description, participants, location) "
        "sunt opționale — dacă sunt furnizate, se salvează un sidecar JSON alături de fișier. "
        "Ingest-ul preia automat fișierul, îl validează, creează înregistrarea "
        "în baza de date și îl trimite la transcriere. "
        "202 Accepted = fișierul a fost primit, procesarea e asincronă."
    ),
)
async def upload_to_inbox(
    file: UploadFile = File(description="Fișierul audio (MP3, WAV, M4A, OGG, FLAC, WEBM)"),
    title: Optional[str] = Form(default=None, description="Titlul ședinței"),
    meeting_date: Optional[str] = Form(default=None, description="Data ședinței (YYYY-MM-DD)"),
    description: Optional[str] = Form(default=None, description="Descriere opțională"),
    participants: Optional[str] = Form(default=None, description="Participanți separați prin virgulă"),
    location: Optional[str] = Form(default=None, description="Locația ședinței"),
) -> InboxUploadResponse:
    """
    Salvează fișierul primit în /data/inbox/.
    Ingest Service monitorizează acest director și preia fișierul automat.
    """
    # Verificare minimă: fișierul trebuie să aibă un nume
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Fișierul trebuie să aibă un nume.",
        )

    # Construim calea destinație: /data/inbox/<filename>
    inbox_path = settings.inbox_path
    inbox_path.mkdir(parents=True, exist_ok=True)

    dest = inbox_path / file.filename

    # Dacă există deja un fișier cu același nume, adăugăm sufix numeric
    # (Ingest-ul va face deduplicare prin SHA256 oricum)
    counter = 1
    original_stem = dest.stem
    original_suffix = dest.suffix
    while dest.exists():
        dest = inbox_path / f"{original_stem}_{counter}{original_suffix}"
        counter += 1

    # Scriem fișierul pe disc în /data/inbox/
    try:
        with dest.open("wb") as out:
            shutil.copyfileobj(file.file, out)
    except OSError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Nu s-a putut salva fișierul: {e}",
        )

    # Dacă s-au furnizat metadate, salvăm un sidecar JSON lângă fișier.
    # Ingest Service va citi acest fișier la procesare.
    meta: dict = {}
    if title:
        meta["title"] = title.strip()
    if meeting_date:
        meta["meeting_date"] = meeting_date.strip()
    if description:
        meta["description"] = description.strip()
    if participants:
        meta["participants"] = [p.strip() for p in participants.split(",") if p.strip()]
    if location:
        meta["location"] = location.strip()

    if meta:
        sidecar_path = dest.with_suffix(dest.suffix + ".meetrec-meta.json")
        try:
            sidecar_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        except OSError as e:
            import logging
            logging.getLogger(__name__).warning("sidecar_write_failed: %s", e)

    return InboxUploadResponse(
        message=(
            "Fișierul a fost primit și va fi procesat în scurt timp. "
            "Înregistrarea va apărea în listă după validare."
        ),
        filename=dest.name,
    )
