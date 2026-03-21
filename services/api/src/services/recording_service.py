# services/api/src/services/recording_service.py
# ============================================================
# Recording Service — Stratul de Business Logic
# ============================================================
# Regula: Router-ul NU știe despre DB. Service-ul NU știe despre HTTP.
# ============================================================

import math
import uuid
from datetime import date
from pathlib import Path
from typing import Optional, List

import structlog
from sqlalchemy import select, func, desc, asc
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

from src.models.recording import Recording, RecordingStatus
from src.schemas.recording import (
    RecordingUpdate, RecordingResponse,
    PaginatedRecordings, RecordingListItem,
)


# Câmpurile permise pentru sortare (protecție împotriva expunerii de coloane interne)
_ALLOWED_SORT_FIELDS = {"created_at", "meeting_date", "title", "duration_seconds", "file_size_bytes"}


class RecordingDeletionError(Exception):
    """Semnalează că înregistrarea nu poate fi ștearsă complet de pe storage."""


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

        # Construim query-ul de bază cu eager loading explicit pentru transcript
        # selectinload = 2 query-uri total (nu N+1) chiar dacă lazy="selectin" e pe model
        query = select(Recording).options(selectinload(Recording.transcript))

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

        # Sortare — validăm că sort_by e un câmp permis
        if sort_by not in _ALLOWED_SORT_FIELDS:
            sort_by = "created_at"
        sort_column = getattr(Recording, sort_by)
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

        total_pages = math.ceil(total / page_size) if total > 0 else 1
        return PaginatedRecordings(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=total_pages,
            has_next=page < total_pages,
            has_prev=page > 1,
        )

    # ── GET BY ID ─────────────────────────────────────────────
    async def get_by_id(self, recording_id: uuid.UUID) -> Optional[Recording]:
        """
        Returnează o înregistrare sau None.
        SQLAlchemy încarcă automat și transcript-ul (lazy="selectin" în model).
        """
        result = await self.db.execute(
            select(Recording).where(Recording.id == recording_id)
        )
        return result.scalar_one_or_none()

    # ── UPDATE ───────────────────────────────────────────────
    async def update(
        self,
        recording_id: uuid.UUID,
        data: RecordingUpdate,
    ) -> Optional[Recording]:
        # SELECT FOR UPDATE = blochează rândul pe durata tranzacției
        # Previne race condition când 2 request-uri PATCH ajung simultan
        result = await self.db.execute(
            select(Recording)
            .where(Recording.id == recording_id)
            .with_for_update()
        )
        recording = result.scalar_one_or_none()
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

        file_path = Path(recording.file_path) if recording.file_path else None

        # 1. Ștergem din DB PRIMUL — dacă aceasta eșuează, fișierul rămâne intact
        # (CASCADE șterge automat și transcript + segmentele)
        await self.db.delete(recording)
        await self.db.flush()

        # 2. Ștergem fișierul DUPĂ ce DB-ul a confirmat ștergerea
        # Dacă unlink() eșuează, logăm dar NU facem rollback DB
        # (un job de cleanup periodic poate relua fișierele orfane)
        if file_path and file_path.is_file():
            try:
                file_path.unlink()
            except OSError as exc:
                logger.error(
                    "orphaned_file_after_delete",
                    path=str(file_path),
                    recording_id=str(recording_id),
                    error=str(exc),
                )

        return True

