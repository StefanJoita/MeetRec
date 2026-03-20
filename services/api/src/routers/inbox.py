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

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
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
        "Ingest-ul preia automat fișierul, îl validează, creează înregistrarea "
        "în baza de date și îl trimite la transcriere. "
        "202 Accepted = fișierul a fost primit, procesarea e asincronă."
    ),
)
async def upload_to_inbox(
    file: UploadFile = File(description="Fișierul audio (MP3, WAV, M4A, OGG, FLAC, WEBM)"),
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

    return InboxUploadResponse(
        message=(
            "Fișierul a fost primit și va fi procesat în scurt timp. "
            "Înregistrarea va apărea în listă după validare."
        ),
        filename=dest.name,
    )
