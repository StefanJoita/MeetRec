# services/api/src/services/recording_service.py
# ============================================================
# Recording Service — Stratul de Business Logic
# ============================================================

import math
import uuid
from pathlib import Path
from typing import Optional, List

import structlog
from sqlalchemy import select, func, desc, asc
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

from src.models.audit_log import User
from src.models.recording import Recording, RecordingParticipant, RecordingStatus
from src.schemas.recording import (
    RecordingUpdate, RecordingResponse,
    PaginatedRecordings, RecordingListItem, ParticipantUserInfo,
)

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
        current_user: Optional[User] = None,
    ) -> PaginatedRecordings:

        query = select(Recording).options(selectinload(Recording.transcript))

        # Participantul vede DOAR înregistrările la care e linkat explicit
        # și doar cele create DUPĂ crearea contului său
        if current_user and current_user.is_participant:
            query = (
                query
                .join(RecordingParticipant, RecordingParticipant.recording_id == Recording.id)
                .where(
                    RecordingParticipant.user_id == current_user.id,
                    Recording.created_at > current_user.created_at,
                )
            )

        if status_filter:
            query = query.where(Recording.status == status_filter)

        if search:
            query = query.where(Recording.title.ilike(f"%{search}%"))

        count_query = select(func.count()).select_from(query.subquery())
        total = await self.db.scalar(count_query) or 0

        if sort_by not in _ALLOWED_SORT_FIELDS:
            sort_by = "created_at"
        sort_column = getattr(Recording, sort_by)
        query = query.order_by(desc(sort_column) if sort_desc else asc(sort_column))

        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        result = await self.db.execute(query)
        recordings = result.scalars().all()

        items = []
        for rec in recordings:
            transcript_status = rec.transcript.status if rec.transcript else None
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
    async def get_by_id(
        self,
        recording_id: uuid.UUID,
        current_user: Optional[User] = None,
    ) -> Optional[Recording]:
        """
        Returnează o înregistrare sau None.
        Dacă userul e participant, verifică accesul în recording_participants.
        """
        if current_user and current_user.is_participant:
            # Verificăm linkul în junction table + constrângerea temporală
            result = await self.db.execute(
                select(Recording)
                .options(selectinload(Recording.transcript))
                .join(RecordingParticipant, RecordingParticipant.recording_id == Recording.id)
                .where(
                    Recording.id == recording_id,
                    RecordingParticipant.user_id == current_user.id,
                    Recording.created_at > current_user.created_at,
                )
            )
            return result.scalar_one_or_none()

        result = await self.db.execute(
            select(Recording).where(Recording.id == recording_id)
        )
        return result.scalar_one_or_none()

    async def to_recording_response(self, recording: Recording) -> RecordingResponse:
        """Convertește modelul Recording la payload API, inclusiv participanții linkați."""
        participants_result = await self.db.execute(
            select(RecordingParticipant, User)
            .join(User, RecordingParticipant.user_id == User.id)
            .where(RecordingParticipant.recording_id == recording.id)
            .order_by(RecordingParticipant.linked_at)
        )
        participant_rows = participants_result.all()

        response = RecordingResponse.model_validate(recording, from_attributes=True)
        response.resolved_participants = [
            ParticipantUserInfo(
                user_id=link.user_id,
                username=user.username,
                full_name=user.full_name,
                email=user.email,
                linked_at=link.linked_at,
            )
            for link, user in participant_rows
        ]
        return response

    # ── UPDATE ───────────────────────────────────────────────
    async def update(
        self,
        recording_id: uuid.UUID,
        data: RecordingUpdate,
        current_user: Optional[User] = None,
    ) -> Optional[Recording]:
        result = await self.db.execute(
            select(Recording)
            .where(Recording.id == recording_id)
            .with_for_update()
        )
        recording = result.scalar_one_or_none()
        if not recording:
            return None

        # Participant nu poate modifica înregistrări
        if current_user and current_user.is_participant:
            return None

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

        await self.db.delete(recording)
        await self.db.flush()

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

    # ── PARTICIPANTS ──────────────────────────────────────────

    async def add_participant(
        self,
        recording_id: uuid.UUID,
        user_id: uuid.UUID,
        linked_by_id: uuid.UUID,
    ) -> bool:
        """
        Leagă un user (participant) de o înregistrare.
        Returnează False dacă legătura există deja (idempotent).
        """
        # Verificăm dacă linkul există deja
        existing = await self.db.execute(
            select(RecordingParticipant).where(
                RecordingParticipant.recording_id == recording_id,
                RecordingParticipant.user_id == user_id,
            )
        )
        if existing.scalar_one_or_none():
            return False

        link = RecordingParticipant(
            recording_id=recording_id,
            user_id=user_id,
            linked_by=linked_by_id,
        )
        self.db.add(link)
        await self.db.flush()
        return True

    async def remove_participant(
        self,
        recording_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> bool:
        """Elimină legătura participant ↔ înregistrare. Returnează False dacă nu există."""
        result = await self.db.execute(
            select(RecordingParticipant).where(
                RecordingParticipant.recording_id == recording_id,
                RecordingParticipant.user_id == user_id,
            )
        )
        link = result.scalar_one_or_none()
        if not link:
            return False

        await self.db.delete(link)
        await self.db.flush()
        return True

    # ── SPEAKER MAPPING ───────────────────────────────────────

    async def update_speaker_mapping(
        self,
        recording_id: str,
        mapping: dict[str, str],
        current_user,
    ) -> Optional[Recording]:
        """
        Actualizează maparea vorbitori → participanți.
        Validează că toți user_id din mapping sunt participanți linkați la înregistrare.
        """
        result = await self.db.execute(
            select(Recording).where(Recording.id == recording_id)
        )
        recording = result.scalar_one_or_none()
        if not recording:
            return None

        # Validăm că toți user_id sunt participanți linkați
        linked_ids = {str(p.user_id) for p in recording.participant_links}
        for speaker, user_id in mapping.items():
            if user_id and user_id not in linked_ids:
                from fastapi import HTTPException
                raise HTTPException(
                    status_code=400,
                    detail=f"Utilizatorul {user_id} nu este participant la această înregistrare.",
                )

        recording.speaker_mapping = mapping
        await self.db.flush()
        return recording
