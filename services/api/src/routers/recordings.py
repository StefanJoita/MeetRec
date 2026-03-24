# services/api/src/routers/recordings.py
# ============================================================
# Router pentru /recordings — CRUD complet + participant management
# ============================================================

import mimetypes
import uuid
from pathlib import Path
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.config import settings
from src.middleware.auth import (
    decode_token, create_audio_token, decode_audio_token,
    get_current_user, get_current_admin, get_current_operator_or_above,
    check_recording_access,
)
from src.models.audit_log import User
from src.models.recording import Recording, RecordingParticipant
from src.schemas.recording import (
    RecordingUpdate, RecordingResponse,
    PaginatedRecordings, ParticipantUserInfo,
)
from src.services.recording_service import RecordingService, RecordingDeletionError
from src.middleware.audit import log_audit
from pydantic import BaseModel

router = APIRouter(
    prefix="/recordings",
    tags=["recordings"],
    dependencies=[Depends(get_current_user)],
    redirect_slashes=False,
)


class ParticipantAdd(BaseModel):
    user_id: uuid.UUID


def get_recording_service(db: AsyncSession = Depends(get_db)) -> RecordingService:
    return RecordingService(db)


# ── GET /recordings ──────────────────────────────────────────
@router.get(
    "/",
    response_model=PaginatedRecordings,
    summary="Listează înregistrările",
)
async def list_recordings(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    sort_by: str = Query(default="created_at"),
    sort_desc: bool = Query(default=True),
    current_user: User = Depends(get_current_user),
    service: RecordingService = Depends(get_recording_service),
    db: AsyncSession = Depends(get_db),
):
    await log_audit(request, db, action="VIEW", resource_type="recordings_list")
    return await service.list_recordings(
        page=page,
        page_size=page_size,
        status_filter=status,
        search=search,
        sort_by=sort_by,
        sort_desc=sort_desc,
        current_user=current_user,
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
    current_user: User = Depends(get_current_user),
    service: RecordingService = Depends(get_recording_service),
    db: AsyncSession = Depends(get_db),
):
    recording = await service.get_by_id(recording_id, current_user=current_user)
    if not recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Înregistrarea cu ID {recording_id} nu există sau nu aveți acces."
        )
    await log_audit(request, db, action="VIEW", resource_type="recording", resource_id=recording_id)
    return await service.to_recording_response(recording)


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
    current_user: User = Depends(get_current_operator_or_above),
    service: RecordingService = Depends(get_recording_service),
):
    recording = await service.update(recording_id, data, current_user=current_user)
    if not recording:
        raise HTTPException(status_code=404, detail="Înregistrarea nu există.")
    return await service.to_recording_response(recording)


# ── DELETE /recordings/{id} ──────────────────────────────────
@router.delete(
    "/{recording_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Șterge o înregistrare",
)
async def delete_recording(
    recording_id: uuid.UUID,
    request: Request,
    _: User = Depends(get_current_admin),
    service: RecordingService = Depends(get_recording_service),
    db: AsyncSession = Depends(get_db),
):
    try:
        success = await service.delete(recording_id)
    except RecordingDeletionError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not success:
        raise HTTPException(status_code=404, detail="Înregistrarea nu există.")
    await log_audit(request, db, action="DELETE", resource_type="recording", resource_id=recording_id)


# ── GET /recordings/{id}/audio-token ─────────────────────────
@router.get(
    "/{recording_id}/audio-token",
    summary="Obține token temporar pentru streaming audio",
)
async def get_audio_token(
    recording_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Returnează un token cu durată de 60 secunde, valid exclusiv pentru
    streaming-ul unui singur fișier audio. Folosit de frontend înainte
    de a seta src-ul elementului <audio>.
    """
    if current_user.is_participant:
        has_access = await check_recording_access(recording_id, current_user, db)
        if not has_access:
            raise HTTPException(status_code=403, detail="Nu aveți acces la acest fișier audio.")

    token = create_audio_token(str(current_user.id), str(recording_id))
    return {"token": token, "expires_in": 60}


# ── GET /recordings/{id}/audio ───────────────────────────────
@router.get(
    "/{recording_id}/audio",
    summary="Streaming fișier audio",
)
async def stream_audio(
    recording_id: uuid.UUID,
    token: str = Query(description="Token audio temporar obținut din /audio-token"),
    db: AsyncSession = Depends(get_db),
):
    """
    Servește fișierul audio. Necesită un token audio de scurtă durată (60s)
    obținut din GET /recordings/{id}/audio-token — nu acceptă JWT-ul principal.
    """
    decoded = decode_audio_token(token)
    if not decoded:
        raise HTTPException(status_code=401, detail="Token audio invalid sau expirat.")

    user_id, token_recording_id = decoded
    if token_recording_id != str(recording_id):
        raise HTTPException(status_code=403, detail="Token nu corespunde acestui fișier audio.")

    result = await db.execute(
        select(User).where(User.id == user_id, User.is_active == True)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Utilizator inexistent.")

    rec_result = await db.execute(
        select(Recording).where(Recording.id == recording_id)
    )
    recording = rec_result.scalar_one_or_none()
    if not recording or not recording.file_path:
        raise HTTPException(status_code=404, detail="Fișierul audio nu există.")

    path = Path(recording.file_path).resolve()
    storage_root = settings.audio_storage_path.resolve()
    if storage_root not in path.parents:
        raise HTTPException(status_code=403, detail="Acces interzis.")

    if not path.exists():
        raise HTTPException(status_code=404, detail="Fișierul audio nu a fost găsit pe disc.")

    media_type, _ = mimetypes.guess_type(str(path))
    return FileResponse(
        path=str(path),
        media_type=media_type or "audio/mpeg",
        filename=path.name,
    )


# ── GET /recordings/{id}/participants ────────────────────────
@router.get(
    "/{recording_id}/participants",
    response_model=List[ParticipantUserInfo],
    summary="Listează participanții linkați la o înregistrare",
)
async def list_participants(
    recording_id: uuid.UUID,
    _: User = Depends(get_current_operator_or_above),
    service: RecordingService = Depends(get_recording_service),
    db: AsyncSession = Depends(get_db),
):
    recording = await service.get_by_id(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Înregistrarea nu există.")

    result = await db.execute(
        select(RecordingParticipant, User)
        .join(User, RecordingParticipant.user_id == User.id)
        .where(RecordingParticipant.recording_id == recording_id)
        .order_by(RecordingParticipant.linked_at)
    )
    rows = result.all()
    return [
        ParticipantUserInfo(
            user_id=link.user_id,
            username=user.username,
            full_name=user.full_name,
            email=user.email,
            linked_at=link.linked_at,
        )
        for link, user in rows
    ]


# ── POST /recordings/{id}/participants ───────────────────────
@router.post(
    "/{recording_id}/participants",
    status_code=status.HTTP_201_CREATED,
    summary="Leagă un participant la o înregistrare",
)
async def add_participant(
    recording_id: uuid.UUID,
    data: ParticipantAdd,
    request: Request,
    current_user: User = Depends(get_current_operator_or_above),
    service: RecordingService = Depends(get_recording_service),
    db: AsyncSession = Depends(get_db),
):
    # Verificăm că înregistrarea există
    recording = await service.get_by_id(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Înregistrarea nu există.")

    # Verificăm că userul există și are rol participant
    user_result = await db.execute(
        select(User).where(User.id == data.user_id, User.is_active == True)
    )
    target_user = user_result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="Utilizatorul nu există sau este inactiv.")
    if not target_user.is_participant:
        raise HTTPException(
            status_code=422,
            detail="Doar utilizatorii cu rol 'participant' pot fi linkați la înregistrări.",
        )

    added = await service.add_participant(
        recording_id=recording_id,
        user_id=data.user_id,
        linked_by_id=current_user.id,
    )
    if not added:
        raise HTTPException(status_code=409, detail="Participantul este deja linkat la această înregistrare.")

    await log_audit(
        request, db,
        action="UPDATE",
        resource_type="recording_participant",
        resource_id=recording_id,
    )
    return {"recording_id": str(recording_id), "user_id": str(data.user_id)}


# ── DELETE /recordings/{id}/participants/{user_id} ───────────
@router.delete(
    "/{recording_id}/participants/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Elimină un participant dintr-o înregistrare",
)
async def remove_participant(
    recording_id: uuid.UUID,
    user_id: uuid.UUID,
    request: Request,
    _: User = Depends(get_current_operator_or_above),
    service: RecordingService = Depends(get_recording_service),
    db: AsyncSession = Depends(get_db),
):
    recording = await service.get_by_id(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Înregistrarea nu există.")

    removed = await service.remove_participant(recording_id=recording_id, user_id=user_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Legătura participant-înregistrare nu există.")

    await log_audit(
        request, db,
        action="DELETE",
        resource_type="recording_participant",
        resource_id=recording_id,
    )
