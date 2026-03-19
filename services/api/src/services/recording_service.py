# services/api/src/services/recording_service.py
# ============================================================
# Recording Service — Stratul de Business Logic
# ============================================================
# Regula: Router-ul NU știe despre DB. Service-ul NU știe despre HTTP.
# ============================================================

import math
import uuid
import hashlib
import shutil
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Optional, List

from fastapi import HTTPException, UploadFile
from sqlalchemy import select, func, or_, desc, asc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.recording import Recording, RecordingStatus
from src.models.transcript import Transcript, TranscriptStatus
from src.schemas.recording import (
    RecordingCreate, RecordingUpdate, RecordingResponse,
    PaginatedRecordings, RecordingListItem, UploadResponse,
)


class RecordingService:

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── LIST ─────────────────────────────────────────────────
    async def list_recordings(
        self,
        page: int = 1,
        page_size: int = 20,
        status_filter: Optional[str] = None,
        search: Optional[str] = None,
        sort_by: str = "created_at",
        sort_desc: bool = True,
    ) -> PaginatedRecordings:

        # Construim query-ul de bază
        # select(Recording) = SELECT * FROM recordings
        query = select(Recording)

        # Adăugăm filtre dacă există
        if status_filter:
            # .where() = WHERE status = 'completed'
            query = query.where(Recording.status == status_filter)

        if search:
            # ilike = LIKE case-insensitive
            # % = wildcard: "%consiliu%" = conține "consiliu" oriunde
            query = query.where(
                Recording.title.ilike(f"%{search}%")
            )

        # Numărăm totalul ÎNAINTE de paginare
        count_query = select(func.count()).select_from(query.subquery())
        total = await self.db.scalar(count_query) or 0

        # Sortare
        sort_column = getattr(Recording, sort_by, Recording.created_at)
        if sort_desc:
            query = query.order_by(desc(sort_column))
        else:
            query = query.order_by(asc(sort_column))

        # Paginare: OFFSET = sărim primele N, LIMIT = luăm maxim M
        # Pagina 1: OFFSET 0,  LIMIT 20  → rândurile 1-20
        # Pagina 2: OFFSET 20, LIMIT 20  → rândurile 21-40
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        result = await self.db.execute(query)
        recordings = result.scalars().all()

        # Construim răspunsul compactat pentru liste
        items = []
        for rec in recordings:
            transcript_status = None
            if rec.transcript:
                transcript_status = rec.transcript.status
            items.append(RecordingListItem(
                id=rec.id,
                title=rec.title,
                meeting_date=rec.meeting_date,
                audio_format=rec.audio_format,
                duration_formatted=rec.duration_formatted,
                file_size_mb=rec.file_size_mb,
                status=rec.status,
                created_at=rec.created_at,
                transcript_status=transcript_status,
            ))

        return PaginatedRecordings(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=math.ceil(total / page_size) if total > 0 else 0,
        )

    # ── GET BY ID ────────────────────────────────────────────
    async def get_by_id(self, recording_id: uuid.UUID) -> Optional[Recording]:
        """
        Returnează o înregistrare sau None.
        SQLAlchemy încarcă automat și transcript-ul (lazy="selectin" în model).
        """
        result = await self.db.execute(
            select(Recording).where(Recording.id == recording_id)
        )
        return result.scalar_one_or_none()

    # ── CREATE ───────────────────────────────────────────────
    async def create(self, data: RecordingCreate) -> Recording:
        """Creează o înregistrare nouă (fără fișier audio)."""
        recording = Recording(
            title=data.title,
            description=data.description,
            meeting_date=data.meeting_date,
            location=data.location,
            participants=data.participants,
            # Câmpuri tehnice — vor fi completate la upload
            original_filename="",
            file_path="",
            file_size_bytes=0,
            file_hash_sha256=str(uuid.uuid4()),  # placeholder
            audio_format="unknown",
            status=RecordingStatus.UPLOADED.value,
        )
        self.db.add(recording)
        await self.db.flush()  # flush = trimite la DB fără commit (obținem ID-ul)

        # Creăm transcript asociat în starea pending
        transcript = Transcript(
            recording_id=recording.id,
            status=TranscriptStatus.PENDING.value,
        )
        self.db.add(transcript)
        await self.db.flush()

        await self.db.refresh(recording, attribute_names=["transcript"])
        return recording

    # ── PROCESS UPLOAD ───────────────────────────────────────
    async def process_upload(
        self,
        recording_id: uuid.UUID,
        file: UploadFile,
    ) -> UploadResponse:
        """
        Procesează un fișier audio uploadat direct prin API.
        Alternativă la ingestia automată din /data/inbox.
        """
        recording = await self.get_by_id(recording_id)
        if not recording:
            raise ValueError("Înregistrarea nu există")

        # Citim fișierul în memorie (pentru hash și stocare)
        # Atenție: pentru fișiere > 100MB, am folosi streaming!
        content = await file.read()
        file_size = len(content)

        # Validare dimensiune
        if file_size > settings.max_file_size_bytes:
            raise ValueError(f"Fișierul depășește limita de 500MB")

        # Hash SHA256
        file_hash = hashlib.sha256(content).hexdigest()

        # Determinăm extensia
        extension = Path(file.filename).suffix.lower().lstrip(".")

        # Salvăm pe disc
        now = datetime.now()
        dest_dir = (
            settings.audio_storage_path
            / str(now.year)
            / f"{now.month:02d}"
            / f"{now.day:02d}"
        )
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / f"{recording_id}.{extension}"

        dest_path.write_bytes(content)

        # Actualizăm înregistrarea
        recording.original_filename = file.filename
        recording.file_path = str(dest_path)
        recording.file_size_bytes = file_size
        recording.file_hash_sha256 = file_hash
        recording.audio_format = extension
        recording.status = RecordingStatus.QUEUED.value

        try:
            await self.db.flush()
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Acest fișier audio a mai fost uploadat anterior.",
            )

        # Publicăm job în Redis
        await self._publish_job(recording)

        return UploadResponse(
            recording_id=recording.id,
            title=recording.title,
            status=recording.status,
            message="Fișierul a fost primit. Transcrierea va începe în scurt timp.",
            estimated_processing_minutes=max(1, (recording.duration_seconds or 300) // 30),
        )

    # ── UPDATE ───────────────────────────────────────────────
    async def update(
        self,
        recording_id: uuid.UUID,
        data: RecordingUpdate,
    ) -> Optional[Recording]:
        recording = await self.get_by_id(recording_id)
        if not recording:
            return None

        # Actualizăm DOAR câmpurile trimise (exclude_unset=True = exclude None-urile)
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(recording, field, value)

        await self.db.flush()
        return recording

    # ── DELETE ───────────────────────────────────────────────
    async def delete(self, recording_id: uuid.UUID) -> bool:
        recording = await self.get_by_id(recording_id)
        if not recording:
            return False

        # Ștergem fișierul fizic de pe disc
        file_path = Path(recording.file_path)
        if file_path.exists():
            file_path.unlink()

        # Ștergem din DB (CASCADE șterge automat și transcript + segmentele)
        await self.db.delete(recording)
        await self.db.flush()
        return True

    # ── PRIVATE ──────────────────────────────────────────────
    async def _publish_job(self, recording: Recording) -> None:
        """Publică job de transcriere în Redis."""
        import json
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        job = {
            "recording_id": str(recording.id),
            "file_path": recording.file_path,
            "audio_format": recording.audio_format,
            "duration_seconds": recording.duration_seconds or 0,
            "language_hint": "ro",
        }
        await r.lpush(settings.redis_transcription_queue, json.dumps(job))
        await r.aclose()