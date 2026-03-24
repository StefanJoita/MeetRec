#/services/api/src/models/recording.py
#===================================================================
#Modelul Recording - mapeaza tabela "recordings" din PostgreSQL
#Fiecare atribut al clasei = o coloana in tabela
#Tipurile python sunt mapate automat la tipuri SQL:
#str - varchar
#int - integer
#datetime - timestamptz
#bool - boolean
#dict (json) - jsonb
#====================================================================

import uuid
from datetime import datetime, date, timezone
from typing import Optional, List
from sqlalchemy import String, Integer, BigInteger, Date, Text, ForeignKey
from sqlalchemy import TIMESTAMP, Enum as SAEnum, JSON, SmallInteger
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy import UniqueConstraint

from src.models.base import Base

#Enumurile din Python - sincronizate cu enumurile din init.sql
import enum

class RecordingStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    VALIDATING= "validating"
    QUEUED = "queued"
    TRANSCRIBING = "transcribing"
    COMPLETED = "completed"
    FAILED= "failed"
    ARCHIVED = "archived"

class AudioFormat(str, enum.Enum):
    WAV     = "wav"
    MP3     = "mp3"
    M4A     = "m4a"
    OGG     = "ogg"
    FLAC    = "flac"
    WEBM    = "webm"
    UNKNOWN = "unknown"

class Recording(Base):
    """
    Modelul principal - o inregistrare audio a unei sedinte
    Relatii:
        recording.transcript  -> obiectul Transcript asociat (1-1)
        (SqlAlchemy gestioneaza automat legatura, nu e nevoie sa o definim explicit)
    """
    __tablename__ = "recordings"
    #identificator unic global, generat automat in Python la crearea obiectului, mapat la UUID in PostgreSQL
    
    #--Identificator------- 
    id: Mapped[uuid.UUID]   = mapped_column(
        PG_UUID(as_uuid=True), 
        primary_key=True, 
        default=uuid.uuid4, #generat automat in python
    )

    #--Informatii despre sedinta------
    title:Mapped[str]=mapped_column(String(255), nullable=False) #titlu descriptiv, nu e secret
    description:Mapped[Optional[str]]=mapped_column(Text, nullable=True) #descriere optionala
    meeting_date:Mapped[date]=mapped_column(Date, nullable=False) #data sedintei
    location:Mapped[Optional[str]]=mapped_column(String(255), nullable=True) #locatia sedintei, optionala

    #participants e un array de stringuri in postgreSQL
    #Ex: ['Alice Ionescu', 'Bob Popescu', 'Charlie Ionescu']
    participants: Mapped[List[str]] = mapped_column(
        ARRAY(String), 
        nullable=True, 
    )

    #--Informatii tehnice despre fisierul audio------
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False) #numele fisierului incarcat
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_hash_sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    audio_format: Mapped[str] = mapped_column(
        SAEnum(AudioFormat, name="audio_format", create_type=False,
               values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sample_rate_hz: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    channels: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)

    # ── Status și erori ────────────────────────────────────
    status: Mapped[str] = mapped_column(
        SAEnum(RecordingStatus, name="recording_status", create_type=False,
               values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=RecordingStatus.UPLOADED.value,
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

     # ── Timestamps ─────────────────────────────────────────
    # server_default=func.now() → PostgreSQL pune timestamp-ul, nu Python
    # (mai precis și consistent chiar dacă ceasul serverului aplicației drifts)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),        # actualizat automat la fiecare UPDATE
        nullable=False,
    )
    retain_until: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
 
    # ── Metadate extra (flexibil) ───────────────────────────
    metadata_: Mapped[Optional[dict]] = mapped_column(
        "metadata",                 # numele coloanei în DB (metadata e rezervat)
        JSON,
        default=dict,
        nullable=True,
    )

    # ── Sesiuni multi-segment ───────────────────────────────
    # Toate segmentele aceleiași ședințe partajează același session_id.
    # Prima înregistrare creată cu un session_id devine "înregistrarea principală".
    # Segmentele ulterioare sunt stocate în recording_audio_segments.
    session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
        unique=True,
        index=True,
    )

    # ── Relații ─────────────────────────────────────────────
    transcript: Mapped[Optional["Transcript"]] = relationship(
        "Transcript",
        back_populates="recording",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # Participanți rezolvați (useri linkați explicit de admin)
    participant_links: Mapped[List["RecordingParticipant"]] = relationship(
        "RecordingParticipant",
        foreign_keys="[RecordingParticipant.recording_id]",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # ── Proprietăți calculate ───────────────────────────────
    @property
    def duration_formatted(self) -> str:
        """Returnează durata ca 'HH:MM:SS'."""
        if not self.duration_seconds:
            return "00:00:00"
        h = self.duration_seconds // 3600
        m = (self.duration_seconds % 3600) // 60
        s = self.duration_seconds % 60
        return f"{h:02d}:{m:02d}:{s:02d}"
 
    @property
    def file_size_mb(self) -> float:
        return round(self.file_size_bytes / (1024 * 1024), 2)
 
    def __repr__(self) -> str:
        return f"<Recording id={str(self.id)[:8]} title='{self.title}' status={self.status}>"


class RecordingAudioSegment(Base):
    """
    Fișiere audio suplimentare pentru o sesiune multi-segment.
    Segmentul 0 este fișierul principal din recordings.file_path.
    Segmentele 1, 2, ... sunt stocate aici, ordonate după segment_index.
    """
    __tablename__ = "recording_audio_segments"
    __table_args__ = (
        UniqueConstraint("recording_id", "segment_index", name="unique_audio_segment"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    recording_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("recordings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    segment_index: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_hash_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<RecordingAudioSegment rec={str(self.recording_id)[:8]} idx={self.segment_index}>"


class RecordingParticipant(Base):
    """
    Tabelă de legătură: care useri (cu rol participant) au acces la care înregistrări.
    Adminul leagă explicit un user de o înregistrare.
    Accesul este acordat doar pentru înregistrări create DUPĂ crearea contului participantului.
    """
    __tablename__ = "recording_participants"

    recording_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("recordings.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    linked_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    # Adminul care a făcut legătura (pentru audit)
    linked_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )

    def __repr__(self) -> str:
        return f"<RecordingParticipant rec={str(self.recording_id)[:8]} user={str(self.user_id)[:8]}>"
