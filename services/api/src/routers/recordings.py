# services/api/src/routers/recordings.py
# ============================================================
# Router pentru /recordings — CRUD complet
# ============================================================
# FastAPI Router = grup de endpoint-uri cu prefix comun
# Toate endpoint-urile de mai jos vor fi la /recordings/...
# ============================================================

import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.schemas.recording import (
    RecordingCreate, RecordingUpdate, RecordingResponse,
    PaginatedRecordings, UploadResponse,
)
from src.services.recording_service import RecordingService
from src.middleware.audit import log_audit

# APIRouter = "mini-aplicație" FastAPI cu prefix și tag-uri
router = APIRouter(
    prefix="/recordings",
    tags=["recordings"],        # grupare în documentația /docs
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


# ── POST /recordings (metadata only) ────────────────────────
@router.post(
    "/",
    response_model=RecordingResponse,
    status_code=status.HTTP_201_CREATED,   # 201 = Created (nu 200 OK)
    summary="Creează o înregistrare",
)
async def create_recording(
    data: RecordingCreate,
    request: Request,
    service: RecordingService = Depends(get_recording_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Creează o înregistrare fără fișier audio (metadata only).
    Fișierul poate fi adăugat ulterior prin /recordings/{id}/upload.
    """
    recording = await service.create(data)
    await log_audit(request, db, action="UPLOAD", resource_type="recording",
                    resource_id=recording.id)
    return recording


# ── POST /recordings/{id}/upload ─────────────────────────────
@router.post(
    "/{recording_id}/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_202_ACCEPTED,  # 202 = Accepted (procesare asincronă)
    summary="Uploadează fișier audio",
)
async def upload_audio(
    recording_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(description="Fișierul audio (WAV, MP3, M4A, etc.)"),
    service: RecordingService = Depends(get_recording_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Uploadează fișierul audio pentru o înregistrare existentă.
    Procesarea (transcrierea) e asincronă — verificați status-ul ulterior.

    202 Accepted = "Am primit cererea, procesăm în fundal"
    (Nu 200 OK — nu e gata imediat!)
    """
    recording = await service.get_by_id(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Înregistrarea nu există.")

    result = await service.process_upload(recording_id, file)
    await log_audit(request, db, action="UPLOAD", resource_type="recording",
                    resource_id=recording_id,
                    details={"filename": file.filename, "size": file.size})
    return result


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
    service: RecordingService = Depends(get_recording_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Șterge o înregistrare și fișierul audio asociat.
    Atenție: operație ireversibilă!
    """
    success = await service.delete(recording_id)
    if not success:
        raise HTTPException(status_code=404, detail="Înregistrarea nu există.")
    await log_audit(request, db, action="DELETE", resource_type="recording",
                    resource_id=recording_id)
    # 204 = returnăm nimic (body gol)