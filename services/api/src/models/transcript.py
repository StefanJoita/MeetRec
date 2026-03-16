# services/api/src/models/transcript.py
import uuid
import enum
from datetime import datetime
from typing import Optional, List

from sqlalchemy import String, Integer, Text, Numeric, ForeignKey, TIMESTAMP, Index
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.models.base import Base


class TranscriptStatus(str, enum.Enum):
    PENDING    = "pending"
    PROCESSING = "processing"
    COMPLETED  = "completed"
    FAILED     = "failed"
    CANCELLED  = "cancelled"


class Transcript(Base):
    """
    Transcriptul generat de STT Worker pentru o înregistrare.
    Relație 1:1 cu Recording (o înregistrare → un transcript activ).
    """
    __tablename__ = "transcripts"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Cheia externă (Foreign Key) → leagă transcriptul de înregistrare
    # ForeignKey("recordings.id") = coloana "id" din tabela "recordings"
    recording_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("recordings.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,                # o înregistrare = maxim un transcript
    )

    # ── Status și limbă ────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TranscriptStatus.PENDING.value
    )
    language: Mapped[Optional[str]] = mapped_column(String(10), default="ro")
    model_used: Mapped[Optional[str]] = mapped_column(String(100))
    model_version: Mapped[Optional[str]] = mapped_column(String(50))

    # ── Statistici ─────────────────────────────────────────
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    confidence_avg: Mapped[Optional[float]] = mapped_column(Numeric(4, 3))
    processing_time_sec: Mapped[Optional[int]] = mapped_column(Integer)

    # ── Full-text search ───────────────────────────────────
    # TSVECTOR = format special PostgreSQL pentru căutare rapidă în text
    # Actualizat automat de trigger-ul din init.sql când se adaugă segmente
    search_vector: Mapped[Optional[str]] = mapped_column(TSVECTOR, nullable=True)

    # ── Timestamps ─────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Relații ────────────────────────────────────────────
    recording: Mapped["Recording"] = relationship(
        "Recording", back_populates="transcript"
    )
    # Un transcript are MULTE segmente (1:N)
    segments: Mapped[List["TranscriptSegment"]] = relationship(
        "TranscriptSegment",
        back_populates="transcript",
        cascade="all, delete-orphan",
        order_by="TranscriptSegment.segment_index",  # ordonate cronologic
        lazy="selectin",
    )

    @property
    def full_text(self) -> str:
        """Textul complet al transcriptului, reconstruit din segmente."""
        return " ".join(seg.text for seg in self.segments)

    @property
    def duration_formatted(self) -> Optional[str]:
        if not self.processing_time_sec:
            return None
        m = self.processing_time_sec // 60
        s = self.processing_time_sec % 60
        return f"{m}m {s}s"


class TranscriptSegment(Base):
    """
    Un segment individual al transcriptului.
    Fiecare rând = o propoziție/frază cu start_time și end_time.
    
    Acestea permit sincronizarea audio ↔ text în UI:
    Click pe "Bună ziua" → audio sare la secunda 12.5
    """
    __tablename__ = "transcript_segments"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    transcript_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("transcripts.id", ondelete="CASCADE"),
        nullable=False,
    )

    # ── Poziție în timp ────────────────────────────────────
    segment_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # Numeric(10,3) = maxim 10 cifre, 3 zecimale
    # Ex: 3742.500 = 3742 secunde și 500 milisecunde
    start_time: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    end_time: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)

    # ── Conținut ───────────────────────────────────────────
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # Scorul de încredere Whisper: 0.0 = "probabil greșit", 1.0 = "sigur"
    confidence: Mapped[Optional[float]] = mapped_column(Numeric(4, 3))
    language: Mapped[Optional[str]] = mapped_column(String(10))

    # Speaker diarization — cine vorbește (opțional, pentru viitor)
    # "SPEAKER_00", "SPEAKER_01" etc.
    speaker_id: Mapped[Optional[str]] = mapped_column(String(50))

    # ── Relație ────────────────────────────────────────────
    transcript: Mapped["Transcript"] = relationship(
        "Transcript", back_populates="segments"
    )

    # Constrângere: în același transcript, indexul e unic
    __table_args__ = (
        # Index compus pentru query-urile de sync audio-transcript
        Index("idx_segments_transcript_time", "transcript_id", "start_time"),
    )

    def __repr__(self) -> str:
        return (f"<Segment [{self.start_time:.1f}s-{self.end_time:.1f}s] "
                f"'{self.text[:30]}...'>" if len(self.text) > 30
                else f"<Segment [{self.start_time:.1f}s-{self.end_time:.1f}s] '{self.text}'>")