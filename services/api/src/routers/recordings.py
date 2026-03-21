# services/api/src/routers/recordings.py
# ============================================================
# Router pentru /recordings — CRUD complet
# ============================================================
# FastAPI Router = grup de endpoint-uri cu prefix comun
# Toate endpoint-urile de mai jos vor fi la /recordings/...
# ============================================================

import mimetypes
import uuid
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status, Request  # noqa: F401
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.middleware.auth import decode_token, get_current_user, get_current_admin
from src.models.audit_log import User
from src.models.recording import Recording
from src.schemas.recording import (
    RecordingUpdate, RecordingResponse,
    PaginatedRecordings,
)
from src.services.recording_service import RecordingService, RecordingDeletionError
from src.middleware.audit import log_audit

# APIRouter = "mini-aplicație" FastAPI cu prefix și tag-uri
router = APIRouter(
    prefix="/recordings",
    tags=["recordings"],        # grupare în documentația /docs
    dependencies=[Depends(get_current_user)],
)


def get_recording_service(db: AsyncSession = Depends(get_db)) -> RecordingService:
    """
    Dependency: furnizează RecordingService cu sesiunea DB injectată.
    FastAPI apelează asta automat pentru fiecare request.
    """
    return RecordingService(db)


# ── GET /recordings ──────────────────────────────────────────
@router.get(
    "/",
    response_model=PaginatedRecordings,
    summary="Listează înregistrările",
    description="Returnează lista paginată a tuturor înregistrărilor audio.",
)
async def list_recordings(
    request: Request,
    # Query parameters opționali cu valori default
    page: int = Query(default=1, ge=1, description="Numărul paginii"),
    page_size: int = Query(default=20, ge=1, le=100, description="Înregistrări per pagină"),
    status: Optional[str] = Query(default=None, description="Filtrează după status"),
    search: Optional[str] = Query(default=None, description="Caută în titlu"),
    sort_by: str = Query(default="created_at", description="Câmpul de sortare"),
    sort_desc: bool = Query(default=True, description="Descrescător?"),
    service: RecordingService = Depends(get_recording_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Listează înregistrările cu paginare, filtrare și sortare.

    Query params exemple:
        GET /recordings?page=2&page_size=10
        GET /recordings?status=completed&sort_by=meeting_date
        GET /recordings?search=consiliu
    """
    await log_audit(request, db, action="VIEW", resource_type="recordings_list")
    return await service.list_recordings(
        page=page,
        page_size=page_size,
        status_filter=status,
        search=search,
        sort_by=sort_by,
        sort_desc=sort_desc,
    )


# ── GET /recordings/{id} ─────────────────────────────────────
@router.get(
    "/{recording_id}",
    response_model=RecordingResponse,
    summary="Obține o înregistrare",
)
async def get_recording(
    recording_id: uuid.UUID,
    request: Request,
    service: RecordingService = Depends(get_recording_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Returnează detaliile complete ale unei înregistrări, inclusiv statusul transcrierii.
    """
    recording = await service.get_by_id(recording_id)
    if not recording:
        # 404 = resursa nu există
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Înregistrarea cu ID {recording_id} nu există."
        )
    await log_audit(request, db, action="VIEW", resource_type="recording",
                    resource_id=recording_id)
    return recording


# ── PATCH /recordings/{id} ───────────────────────────────────
@router.patch(
    "/{recording_id}",
    response_model=RecordingResponse,
    summary="Actualizează o înregistrare",
)
async def update_recording(
    recording_id: uuid.UUID,
    data: RecordingUpdate,
    request: Request,
    service: RecordingService = Depends(get_recording_service),
):
    """
    Actualizează parțial metadata unei înregistrări.
    PATCH (nu PUT): trimiți DOAR câmpurile de modificat.
    Ex: {"title": "Titlu nou"} → modifică doar titlul
    """
    recording = await service.update(recording_id, data)
    if not recording:
        raise HTTPException(status_code=404, detail="Înregistrarea nu există.")
    return recording


# ── DELETE /recordings/{id} ──────────────────────────────────
@router.delete(
    "/{recording_id}",
    status_code=status.HTTP_204_NO_CONTENT,  # 204 = No Content (succes fără body)
    summary="Șterge o înregistrare",
)
async def delete_recording(
    recording_id: uuid.UUID,
    request: Request,
    _: User = Depends(get_current_admin),
    service: RecordingService = Depends(get_recording_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Șterge o înregistrare și fișierul audio asociat.
    Atenție: operație ireversibilă!
    """
    try:
        success = await service.delete(recording_id)
    except RecordingDeletionError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    if not success:
        raise HTTPException(status_code=404, detail="Înregistrarea nu există.")
    await log_audit(request, db, action="DELETE", resource_type="recording",
                    resource_id=recording_id)
    # 204 = returnăm nimic (body gol)


# ── GET /recordings/{id}/audio ───────────────────────────────
@router.get(
    "/{recording_id}/audio",
    summary="Streaming fișier audio",
    tags=["recordings"],
)
async def stream_audio(
    recording_id: uuid.UUID,
    token: str = Query(description="JWT token pentru autentificare"),
    db: AsyncSession = Depends(get_db),
):
    """
    Servește fișierul audio al unei înregistrări.
    Autentificarea se face prin query param ?token=JWT
    (necesar deoarece <audio> HTML nu trimite header-uri custom).
    """
    # Validare token manual (nu prin Depends — vine ca query param)
    user_id = decode_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Token invalid sau expirat.")

    result = await db.execute(
        select(User).where(User.id == user_id, User.is_active == True)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=401, detail="Utilizator inexistent.")

    # Obținem înregistrarea direct (cu file_path)
    rec_result = await db.execute(
        select(Recording).where(Recording.id == recording_id)
    )
    recording = rec_result.scalar_one_or_none()
    if not recording or not recording.file_path:
        raise HTTPException(status_code=404, detail="Fișierul audio nu există.")

    path = Path(recording.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Fișierul audio nu a fost găsit pe disc.")

    media_type, _ = mimetypes.guess_type(str(path))
    return FileResponse(
        path=str(path),
        media_type=media_type or "audio/mpeg",
        filename=path.name,
    )