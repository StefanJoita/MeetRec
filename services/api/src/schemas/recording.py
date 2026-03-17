# services/api/src/schemas/recording.py
# ============================================================
# Pydantic Schemas — Contractele API-ului
# ============================================================
# Pydantic 101:
#   - Validare automată: dacă trimiți string în loc de int → 422 automat
#   - Serializare: obiect Python → JSON automat
#   - Documentare: FastAPI generează /docs din aceste scheme
#
# Tipuri de scheme:
#   *Create  = ce primim de la client când CREEAZĂ o resursă
#   *Update  = ce primim de la client când ACTUALIZEAZĂ
#   *Response = ce trimitem clientului ca răspuns
#   *List    = răspuns pentru liste (cu paginare)
# ============================================================

import uuid
from datetime import datetime, date
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator, ConfigDict


# ── SEGMENT ─────────────────────────────────────────────────

class SegmentResponse(BaseModel):
    """Ce vede utilizatorul pentru un segment de transcript."""
    id: uuid.UUID
    segment_index: int
    start_time: float
    end_time: float
    text: str
    confidence: Optional[float] = None
    speaker_id: Optional[str] = None
    language: Optional[str] = None

    # ConfigDict spune Pydantic să poată citi și din obiecte SQLAlchemy
    # (nu doar din dict-uri)
    model_config = ConfigDict(from_attributes=True)


# ── TRANSCRIPT ───────────────────────────────────────────────

class TranscriptResponse(BaseModel):
    """Transcriptul complet cu toate segmentele."""
    id: uuid.UUID
    recording_id: uuid.UUID
    status: str
    language: Optional[str]
    model_used: Optional[str]
    word_count: int
    confidence_avg: Optional[float]
    processing_time_sec: Optional[int]
    created_at: datetime
    completed_at: Optional[datetime]
    segments: List[SegmentResponse] = []
    full_text: Optional[str] = None   # proprietatea calculată din model

    model_config = ConfigDict(from_attributes=True)


class TranscriptSummary(BaseModel):
    """Rezumat scurt al transcriptului — folosit în lista înregistrărilor."""
    id: uuid.UUID
    status: str
    word_count: int
    completed_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


# ── RECORDING — INPUT ────────────────────────────────────────

class RecordingCreate(BaseModel):
    """
    Ce trimite clientul când creează manual o înregistrare.
    (Alternativ la ingestia automată din /inbox)
    """
    title: str = Field(
        min_length=3,
        max_length=500,
        description="Titlul ședinței",
        examples=["Ședința Consiliului Local — 15 Ianuarie 2024"]
    )
    meeting_date: date = Field(description="Data ședinței")
    description: Optional[str] = Field(None, max_length=5000)
    location: Optional[str] = Field(None, max_length=255)
    participants: Optional[List[str]] = Field(
        None,
        description="Lista participanților",
        examples=[["Ion Ionescu", "Maria Pop"]]
    )

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        """Validare custom: titlul nu poate fi doar spații."""
        if not v.strip():
            raise ValueError("Titlul nu poate fi gol sau conține doar spații")
        return v.strip()

    @field_validator("meeting_date")
    @classmethod
    def date_not_future(cls, v: date) -> date:
        """O ședință nu poate fi în viitor."""
        if v > date.today():
            raise ValueError("Data ședinței nu poate fi în viitor")
        return v


class RecordingUpdate(BaseModel):
    """
    Ce poate fi actualizat după creare.
    Toate câmpurile sunt Optional (PATCH semantic — actualizezi doar ce trimiți).
    """
    title: Optional[str] = Field(None, min_length=3, max_length=500)
    description: Optional[str] = None
    meeting_date: Optional[date] = None
    location: Optional[str] = None
    participants: Optional[List[str]] = None


# ── RECORDING — OUTPUT ───────────────────────────────────────

class RecordingResponse(BaseModel):
    """
    Ce vede utilizatorul când cere o înregistrare specifică.
    Include toate câmpurile relevante, dar NU file_path (securitate!).
    """
    id: uuid.UUID
    title: str
    description: Optional[str]
    meeting_date: date
    location: Optional[str]
    participants: Optional[List[str]]
    original_filename: str
    # file_path NU e inclus — nu vrem să expunem căile de pe server
    file_size_bytes: int
    audio_format: str
    duration_seconds: Optional[int]
    duration_formatted: str        # proprietate calculată: "01:02:35"
    file_size_mb: float            # proprietate calculată: 45.2
    status: str
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime
    retain_until: Optional[date]
    transcript: Optional[TranscriptSummary] = None

    model_config = ConfigDict(from_attributes=True)


class RecordingListItem(BaseModel):
    """
    Versiune compactă pentru liste — mai puțini câmpi, răspuns mai mic.
    """
    id: uuid.UUID
    title: str
    meeting_date: date
    audio_format: str
    duration_formatted: str
    file_size_mb: float
    status: str
    created_at: datetime
    transcript_status: Optional[str] = None   # extras din relație

    model_config = ConfigDict(from_attributes=True)


class PaginatedRecordings(BaseModel):
    """
    Răspuns paginat pentru lista de înregistrări.
    Paginare = nu trimitem 10.000 înregistrări deodată → trimitem 20 câte 20.
    """
    items: List[RecordingListItem]
    total: int           # total înregistrări (pentru UI să știe câte pagini sunt)
    page: int
    page_size: int
    pages: int           # total pagini = ceil(total / page_size)


# ── SEARCH ───────────────────────────────────────────────────

class SearchResult(BaseModel):
    """Un rezultat de căutare în transcrieri."""
    recording_id: uuid.UUID
    recording_title: str
    meeting_date: date
    segment_id: uuid.UUID
    start_time: float
    end_time: float
    text: str                   # fragmentul de text care conține cuvântul căutat
    headline: Optional[str] = None  # fragmentul cu cuvântul evidențiat (<b>cuvânt</b>)
    rank: float = 0.0           # scorul de relevanță (mai mare = mai relevant)

    model_config = ConfigDict(from_attributes=True)


class SearchResponse(BaseModel):
    query: str
    results: List[SearchResult]
    total_results: int
    search_time_ms: int


# ── UPLOAD RESPONSE ──────────────────────────────────────────

class UploadResponse(BaseModel):
    """Răspunsul la upload-ul unui fișier audio."""
    recording_id: uuid.UUID
    title: str
    status: str
    message: str
    estimated_processing_minutes: int


# ── AUTH ─────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int             # secunde până la expirare