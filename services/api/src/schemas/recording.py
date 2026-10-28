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
from pydantic import BaseModel, Field, ConfigDict

from src.services.classification import ClassificationCode


class ParticipantUserInfo(BaseModel):
    """User linkat ca participant la o înregistrare."""
    user_id: uuid.UUID
    username: str
    full_name: Optional[str]
    email: str
    linked_at: datetime

    model_config = ConfigDict(from_attributes=True)


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
    segments: List[SegmentResponse] = Field(default_factory=list)
    full_text: Optional[str] = None   # proprietatea calculată din model

    model_config = ConfigDict(from_attributes=True)


class TranscriptSummary(BaseModel):
    """Rezumat scurt al transcriptului — folosit în lista înregistrărilor."""
    id: uuid.UUID
    status: str
    word_count: int
    completed_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


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
    classification: Optional[ClassificationCode] = None


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
    classification: str
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
    resolved_participants: List[ParticipantUserInfo] = Field(default_factory=list)
    speaker_mapping: dict[str, str] = Field(default_factory=dict)

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
    classification: str
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
    has_next: bool       # există pagina următoare?
    has_prev: bool       # există pagina anterioară?


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
    speaker_id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class SearchResponse(BaseModel):
    query: str
    results: List[SearchResult]
    total_results: int   # total segmente care corespund query-ului (înainte de LIMIT)
    offset: int
    limit: int
    pages: int
    search_time_ms: int


class SemanticSearchResult(BaseModel):
    """Un rezultat de căutare semantică — similar cu SearchResult dar fără headline FTS."""
    recording_id: uuid.UUID
    recording_title: str
    meeting_date: date
    segment_id: uuid.UUID
    start_time: float
    end_time: float
    text: str
    similarity: float   # 0.0 - 1.0 (1.0 = identic semantic)
    speaker_id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class SemanticSearchResponse(BaseModel):
    query: str
    results: List[SemanticSearchResult]
    total_results: int
    limit: int
    search_time_ms: int
    semantic_available: bool = True     # False: search-indexer indisponibil


class CombinedSearchResult(BaseModel):
    """Rezultat combinat FTS + semantic."""
    recording_id: uuid.UUID
    recording_title: str
    meeting_date: date
    segment_id: uuid.UUID
    start_time: float
    end_time: float
    text: str
    headline: Optional[str] = None   # din FTS (None dacă doar semantic)
    rank: Optional[float] = None     # scor FTS
    similarity: Optional[float] = None  # scor semantic 0.0-1.0
    source: str                      # "fts", "semantic", "both"
    score: float = 0.0               # Reciprocal Rank Fusion (pozițiile din ambele căutări)
    speaker_id: Optional[str] = None
    speaker_name: Optional[str] = None   # persoana asociată sau „Vorbitor N”

    model_config = ConfigDict(from_attributes=True)


class SearchGroup(BaseModel):
    """Rezultatele dintr-o ședință: cele mai relevante fragmente + câte sunt în total."""
    recording_id: uuid.UUID
    recording_title: str
    meeting_date: date
    score: float
    total_hits: int
    hits: List[CombinedSearchResult]


class RecordingMatch(BaseModel):
    """Ședință găsită după titlu, descriere, locație sau participanți."""
    recording_id: uuid.UUID
    title: str
    meeting_date: date
    location: Optional[str] = None
    headline: Optional[str] = None


class CombinedSearchResponse(BaseModel):
    query: str
    groups: List[SearchGroup]            # pagina curentă, grupat pe ședință
    recordings: List[RecordingMatch]     # potriviri în titlu / detalii
    total_groups: int                    # câte ședințe au fragmente găsite
    total_hits: int                      # câte fragmente în total
    page: int
    page_size: int
    pages: int
    fts_count: int       # fragmente găsite de căutarea exactă
    semantic_count: int  # fragmente găsite după sens
    both_count: int      # găsite de ambele
    semantic_available: bool             # False: căutarea după sens nu a răspuns
    search_time_ms: int


# ── AUTH ─────────────────────────────────────────────────────

class SpeakerMappingUpdate(BaseModel):
    """Mapare vorbitori diarizare → participanți linkați sau nume scrise liber."""
    mapping: dict[str, str] = Field(
        description="SPEAKER_XX → id-ul unui participant linkat (UUID) sau un nume (maxim 100 de caractere)",
        default_factory=dict
    )


class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int             # secunde până la expirare