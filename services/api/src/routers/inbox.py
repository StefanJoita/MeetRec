# services/api/src/routers/inbox.py
# ============================================================
# Router /inbox — Poarta de intrare pentru fișiere audio
# ============================================================
# Arhitectura:
#   Client → POST /inbox/session/create → API creează Recording în DB
#   Client → POST /inbox/upload (paralel) → API salvează în /data/inbox/ + sidecar
#   Ingest Service detectează (inotify) → validează → DB → Redis
#   Client → POST /inbox/session/{id}/complete → API dispatchează la Redis
#
# Suport sesiuni multi-segment:
#   Clientul înregistrează sesiunea o singură dată (cu toate metadatele),
#   primește session_id, apoi trimite segmente audio fără a repeta metadatele.
#   Recording-ul există în DB imediat, eliminând retry-urile pentru 404.
# ============================================================

import asyncio
import hashlib
import json
import shutil
import uuid as uuid_lib
from datetime import date, datetime, timezone
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
from src.models.recording import Recording, RecordingAudioSegment, RecordingStatus
from src.models.transcript import Transcript

router = APIRouter(
    prefix="/inbox",
    tags=["inbox"],
    dependencies=[Depends(get_current_user)],
)


class SessionCreateRequest(BaseModel):
    title: str
    meeting_date: str          # YYYY-MM-DD
    participants: Optional[str] = None   # virgulă-separați
    location: Optional[str] = None
    room_name: Optional[str] = None


class SessionCreateResponse(BaseModel):
    session_id: str
    recording_id: str


class InboxUploadResponse(BaseModel):
    """Răspuns la upload: fișierul a fost primit și va fi procesat."""
    message: str
    filename: str
    recording_id: Optional[str] = None
    session_id: Optional[str] = None
    segment_index: Optional[int] = None
    is_new_session: Optional[bool] = None


class SessionCompleteRequest(BaseModel):
    total_segments: int


class SessionCompleteResponse(BaseModel):
    status: str
    recording_id: str


@router.post(
    "/session/create",
    response_model=SessionCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Pre-înregistrează o sesiune de înregistrare",
    description=(
        "Creează un Recording în DB cu metadatele sesiunii înainte ca vreun fișier audio "
        "să sosească. Clientul obține session_id și poate începe să trimită segmente audio "
        "fără a mai include metadatele în fiecare upload. Elimină retry-urile pentru 404 "
        "la /complete, deoarece Recording-ul există deja în DB."
    ),
)
async def create_session(
    body: SessionCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> SessionCreateResponse:
    session_id = uuid_lib.uuid4()

    # Hash placeholder unic derivat din session_id — va fi suprascris de Ingest
    # când procesează primul segment audio real.
    placeholder_hash = hashlib.sha256(str(session_id).encode()).hexdigest()

    try:
        meeting_date_val = date.fromisoformat(body.meeting_date)
    except ValueError:
        meeting_date_val = datetime.now(timezone.utc).date()

    participants_list = (
        [p.strip() for p in body.participants.split(",") if p.strip()]
        if body.participants
        else None
    )

    recording = Recording(
        id=session_id,           # recording.id == session_id pentru sesiuni pre-înregistrate
        session_id=session_id,
        title=body.title,
        meeting_date=meeting_date_val,
        location=body.location,
        participants=participants_list,
        original_filename=f"session_{session_id}.wav",   # placeholder
        file_path="",                                     # completat de Ingest
        file_size_bytes=0,                                # completat de Ingest
        file_hash_sha256=placeholder_hash,                # completat de Ingest
        audio_format="wav",
        status=RecordingStatus.SESSION_REGISTERED,
        last_segment_at=datetime.now(timezone.utc),
        metadata_={"room_name": body.room_name} if body.room_name else None,
    )
    db.add(recording)

    transcript = Transcript(
        recording_id=session_id,
        status="pending",
        language="ro",
    )
    db.add(transcript)

    await db.commit()

    return SessionCreateResponse(
        session_id=str(session_id),
        recording_id=str(session_id),
    )


@router.post(
    "/upload",
    response_model=InboxUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trimite fișier audio la transcriere",
    description=(
        "Salvează fișierul în inbox-ul monitorizat de Ingest Service. "
        "Dacă sesiunea a fost pre-înregistrată via /session/create, metadatele "
        "(title, participants etc.) nu mai trebuie trimise — session_id este suficient. "
        "202 Accepted = fișierul a fost primit, procesarea e asincronă."
    ),
)
async def upload_to_inbox(
    file: UploadFile = File(description="Fișierul audio (MP3, WAV, M4A, OGG, FLAC, WEBM)"),
    session_id: Optional[str] = Form(default=None),
    segment_index: Optional[str] = Form(default=None),
    is_final: Optional[str] = Form(default=None),
    total_segments: Optional[str] = Form(default=None),
    # Câmpurile de mai jos sunt opționale — folosite doar dacă sesiunea NU a fost pre-înregistrată
    title: Optional[str] = Form(default=None),
    meeting_date: Optional[str] = Form(default=None),
    description: Optional[str] = Form(default=None),
    participants: Optional[str] = Form(default=None),
    location: Optional[str] = Form(default=None),
    room_name: Optional[str] = Form(default=None),
    db: AsyncSession = Depends(get_db),
) -> InboxUploadResponse:
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
                detail="session_id trebuie să fie un UUID valid.",
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

    # ── Sidecar JSON ──────────────────────────────────────────
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
    if room_name:
        meta["room_name"] = room_name.strip()
    if parsed_session_id is not None:
        meta["session_id"] = parsed_session_id
    if parsed_segment_index is not None:
        meta["segment_index"] = parsed_segment_index
    if total_segments is not None:
        try:
            meta["total_segments"] = int(total_segments)
        except ValueError:
            pass
    if existing_recording_id is not None:
        meta["existing_recording_id"] = existing_recording_id

    if meta:
        sidecar_path = dest.with_suffix(dest.suffix + ".meetrec-meta.json")
        try:
            sidecar_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        except OSError as e:
            import logging
            logging.getLogger(__name__).warning("sidecar_write_failed: %s", e)

    if existing_recording_id:
        message = "Segment atașat sesiunii existente. Va fi procesat și adăugat la transcriptul înregistrării."
    else:
        message = "Fișierul a fost primit și va fi procesat în scurt timp."

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
    summary="Marchează sesiunea ca completă și lansează transcrierea",
    description=(
        "Apelat de client după ce toate segmentele au primit 202 OK la upload. "
        "Recording-ul este garantat să existe (creat de /session/create sau de Ingest). "
        "Serverul verifică că Ingest a stocat toate segmentele așteptate, "
        "apoi publică jobul de transcriere în Redis."
    ),
)
async def complete_session(
    session_id: str,
    body: SessionCompleteRequest,
    db: AsyncSession = Depends(get_db),
) -> SessionCompleteResponse:
    try:
        parsed_session_id = uuid_lib.UUID(session_id.strip())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="session_id trebuie să fie un UUID valid.",
        )

    if body.total_segments < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="total_segments trebuie să fie cel puțin 1.",
        )

    result = await db.execute(
        select(Recording).where(Recording.session_id == parsed_session_id)
    )
    recording = result.scalar_one_or_none()
    if recording is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sesiunea nu a fost găsită.",
        )

    recording_id = str(recording.id)

    if recording.status not in (
        RecordingStatus.SESSION_REGISTERED,
        RecordingStatus.QUEUED,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Sesiunea are deja status '{recording.status}' — nu mai poate fi dispatchată.",
        )

    # ── Verificare că Ingest a stocat toate segmentele ──────────
    # Segment 0 = recordings.file_path (verificăm că nu mai e placeholder)
    # Segmente 1..N-1 = recording_audio_segments
    extra_segments_expected = body.total_segments - 1

    # Așteptăm până când Ingest procesează cel puțin segmentul 0 (status devine 'queued')
    # și toate segmentele suplimentare sunt stocate. Polling maxim 15s.
    for _ in range(15):
        await db.refresh(recording)
        if recording.status == RecordingStatus.SESSION_REGISTERED:
            # Ingest încă nu a procesat segmentul 0
            await asyncio.sleep(1)
            continue

        if extra_segments_expected > 0:
            stored_result = await db.execute(
                select(func.count(RecordingAudioSegment.id)).where(
                    RecordingAudioSegment.recording_id == recording.id,
                )
            )
            stored_count = stored_result.scalar_one()
            if stored_count >= extra_segments_expected:
                break
            await asyncio.sleep(1)
        else:
            break

    # Verificare finală
    await db.refresh(recording)
    if recording.status == RecordingStatus.SESSION_REGISTERED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Segmentul 0 încă în procesare de Ingest după 15s. Reîncearcă.",
        )

    # Segmentele extra lipsă după timeout = respinse de ingest (prea scurte, duplicate etc.)
    # Dispatchăm oricum cu ce avem — STT worker concatenează segmentele disponibile.
    import logging as _logging
    if extra_segments_expected > 0:
        stored_result = await db.execute(
            select(func.count(RecordingAudioSegment.id)).where(
                RecordingAudioSegment.recording_id == recording.id,
            )
        )
        stored_count = stored_result.scalar_one()
        if stored_count < extra_segments_expected:
            missing = extra_segments_expected - stored_count
            _logging.getLogger(__name__).warning(
                "complete_dispatching_with_missing_segments recording_id=%s expected=%d stored=%d missing=%d",
                recording_id, extra_segments_expected, stored_count, missing,
            )

    # ── Dispatch la Redis ──────────────────────────────────────
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
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Redis temporar indisponibil: {e}. Reîncearcă.",
        )

    recording.status = RecordingStatus.TRANSCRIBING
    recording.last_segment_at = None
    await db.commit()

    return SessionCompleteResponse(status="dispatched", recording_id=recording_id)
