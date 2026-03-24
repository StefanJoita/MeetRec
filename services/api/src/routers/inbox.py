# services/api/src/routers/inbox.py
# ============================================================
# Router /inbox — Poarta de intrare pentru fișiere audio
# ============================================================
# Arhitectura:
#   Client → POST /inbox/upload → API salvează în /data/inbox/ + sidecar
#   Ingest Service detectează (inotify) → validează → DB → Redis
#
# Suport sesiuni multi-segment:
#   Dacă session_id e prezent, API verifică dacă există deja o înregistrare
#   cu acel session_id. Dacă DA, include existing_recording_id în sidecar
#   astfel încât Ingest să atașeze fișierul ca segment suplimentar,
#   fără să creeze o înregistrare separată.
# ============================================================

import json
import shutil
import uuid as uuid_lib
from pathlib import Path
from typing import Optional

import redis as redis_sync
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import get_db
from src.middleware.auth import get_current_user
from src.models.recording import Recording, RecordingAudioSegment

router = APIRouter(
    prefix="/inbox",
    tags=["inbox"],
    dependencies=[Depends(get_current_user)],
)


class InboxUploadResponse(BaseModel):
    """Răspuns la upload: fișierul a fost primit și va fi procesat."""
    message: str
    filename: str
    recording_id: Optional[str] = None   # prezent dacă session_id e cunoscut
    session_id: Optional[str] = None
    segment_index: Optional[int] = None
    is_new_session: Optional[bool] = None  # True = sesiune nouă, False = segment atașat


class SessionCompleteResponse(BaseModel):
    status: str
    recording_id: str


@router.post(
    "/upload",
    response_model=InboxUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trimite fișier audio la transcriere",
    description=(
        "Salvează fișierul în inbox-ul monitorizat de Ingest Service. "
        "Câmpurile session_id și segment_index permit trimiterea unei ședințe "
        "în mai multe segmente audio — toate vor fi atașate la aceeași înregistrare. "
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
    session_id: Optional[str] = Form(
        default=None,
        description="UUID al sesiunii de înregistrare. Toate segmentele aceleiași ședințe au același session_id.",
    ),
    segment_index: Optional[str] = Form(
        default=None,
        description="Ordinea segmentului în sesiune: '0', '1', '2', etc.",
    ),
    db: AsyncSession = Depends(get_db),
) -> InboxUploadResponse:
    """
    Salvează fișierul primit în /data/inbox/.
    Ingest Service monitorizează acest director și preia fișierul automat.

    Dacă session_id e prezent și există deja o înregistrare cu acel session_id,
    fișierul este marcat ca segment suplimentar al înregistrării existente.
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Fișierul trebuie să aibă un nume.",
        )

    # ── Validare session_id și segment_index ──────────────────
    parsed_session_id: Optional[str] = None
    parsed_segment_index: Optional[int] = None

    if session_id is not None:
        try:
            parsed_session_id = str(uuid_lib.UUID(session_id.strip()))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="session_id trebuie să fie un UUID valid (ex: '550e8400-e29b-41d4-a716-446655440000').",
            )

    if segment_index is not None:
        try:
            parsed_segment_index = int(segment_index.strip())
            if parsed_segment_index < 0:
                raise ValueError
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="segment_index trebuie să fie un număr întreg pozitiv.",
            )

    # ── Verificare sesiune existentă în DB ────────────────────
    existing_recording_id: Optional[str] = None
    is_new_session: Optional[bool] = None

    if parsed_session_id is not None:
        result = await db.execute(
            select(Recording.id).where(Recording.session_id == uuid_lib.UUID(parsed_session_id))
        )
        row = result.scalar_one_or_none()
        if row is not None:
            existing_recording_id = str(row)
            is_new_session = False
        else:
            is_new_session = True

    # ── Salvare fișier în /data/inbox/ ────────────────────────
    inbox_path = settings.inbox_path
    inbox_path.mkdir(parents=True, exist_ok=True)

    dest = inbox_path / file.filename

    counter = 1
    original_stem = dest.stem
    original_suffix = dest.suffix
    while dest.exists():
        dest = inbox_path / f"{original_stem}_{counter}{original_suffix}"
        counter += 1

    try:
        with dest.open("wb") as out:
            shutil.copyfileobj(file.file, out)
    except OSError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Nu s-a putut salva fișierul: {e}",
        )

    # ── Sidecar JSON (metadate + sesiune) ─────────────────────
    # Ingest Service citește acest fișier la procesare.
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
    if parsed_session_id is not None:
        meta["session_id"] = parsed_session_id
    if parsed_segment_index is not None:
        meta["segment_index"] = parsed_segment_index
    if existing_recording_id is not None:
        # Ingest știe că trebuie să atașeze, nu să creeze înregistrare nouă
        meta["existing_recording_id"] = existing_recording_id

    # Scriem sidecar-ul dacă avem orice metadate (inclusiv sesiune)
    if meta:
        sidecar_path = dest.with_suffix(dest.suffix + ".meetrec-meta.json")
        try:
            sidecar_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        except OSError as e:
            import logging
            logging.getLogger(__name__).warning("sidecar_write_failed: %s", e)

    # ── Răspuns ───────────────────────────────────────────────
    if existing_recording_id:
        message = (
            "Segment atașat sesiunii existente. "
            "Va fi procesat și adăugat la transcriptul înregistrării."
        )
    else:
        message = (
            "Fișierul a fost primit și va fi procesat în scurt timp. "
            "Înregistrarea va apărea în listă după validare."
        )

    return InboxUploadResponse(
        message=message,
        filename=dest.name,
        recording_id=existing_recording_id,
        session_id=parsed_session_id,
        segment_index=parsed_segment_index,
        is_new_session=is_new_session,
    )


@router.post(
    "/session/{session_id}/complete",
    response_model=SessionCompleteResponse,
    status_code=status.HTTP_200_OK,
    summary="Marchează sesiunea ca completă și lansează transcrierea imediat",
    description=(
        "Apelat de client după ce toate segmentele au primit 200 OK la upload. "
        "Serverul verifică că Ingest a stocat toate segmentele așteptate, "
        "apoi publică imediat jobul de transcriere în Redis. "
        "Session Watcher rămâne activ ca safety net pentru sesiuni abandonate."
    ),
)
async def complete_session(
    session_id: str,
    recording_id: str = Form(description="ID-ul înregistrării principale (returnat la segment_index ≥ 1)"),
    total_segments: int = Form(
        description="Numărul total de segmente ale sesiunii (inclusiv segment 0). "
                    "Serverul verifică că are exact acest număr înainte de a dispatcha."
    ),
    db: AsyncSession = Depends(get_db),
) -> SessionCompleteResponse:
    # ── Validare session_id ────────────────────────────────────
    try:
        parsed_session_id = uuid_lib.UUID(session_id.strip())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="session_id trebuie să fie un UUID valid.",
        )

    if total_segments < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="total_segments trebuie să fie cel puțin 1.",
        )

    # ── Verificare recording există și aparține sesiunii ───────
    result = await db.execute(
        select(Recording).where(
            Recording.id == uuid_lib.UUID(recording_id),
            Recording.session_id == parsed_session_id,
        )
    )
    recording = result.scalar_one_or_none()
    if recording is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Înregistrarea nu a fost găsită sau nu aparține acestei sesiuni.",
        )

    # ── Verificare că sesiunea nu e deja dispatchată ───────────
    if recording.status not in ("queued",):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Sesiunea are deja status '{recording.status}' — nu mai poate fi dispatchată.",
        )

    # ── Verificare că Ingest a stocat toate segmentele ──────────
    # Segment 0 = recordings (întotdeauna prezent dacă am ajuns aici)
    # Segmente 1..N-1 = recording_audio_segments (câte rânduri există)
    # Verificăm numărul de rânduri, nu statusul lor — ingest setează 'queued'
    # imediat după stocare, STT Worker îl schimbă în 'completed' mai târziu.
    extra_segments_expected = total_segments - 1
    if extra_segments_expected > 0:
        stored_result = await db.execute(
            select(func.count(RecordingAudioSegment.id)).where(
                RecordingAudioSegment.recording_id == uuid_lib.UUID(recording_id),
            )
        )
        stored_count = stored_result.scalar_one()
        if stored_count < extra_segments_expected:
            missing = extra_segments_expected - stored_count
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"{missing} segment(e) încă în procesare de Ingest. Reîncearcă în câteva secunde.",
            )

    # ── Marcare + dispatch ─────────────────────────────────────
    # Același pattern ca Session Watcher: marchează ÎNAINTE de publish (idempotență)
    recording.status = "transcribing"
    recording.last_segment_at = None  # exclude din query-ul Session Watcher
    await db.commit()

    try:
        r = redis_sync.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_timeout=5,
        )
        job = json.dumps({
            "recording_id": recording_id,
            "session_mode": True,
            "language_hint": "ro",
        })
        r.lpush(settings.redis_transcription_queue, job)
        r.close()
    except redis_sync.RedisError as e:
        # Rollback status — Session Watcher va prelua în max 30s
        recording.status = "queued"
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Redis temporar indisponibil: {e}. Reîncearcă.",
        )

    return SessionCompleteResponse(status="dispatched", recording_id=recording_id)
