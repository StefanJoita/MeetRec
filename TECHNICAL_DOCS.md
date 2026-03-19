# MeetRec — Technical Documentation

> **Meeting Recording & Transcription Platform**
> Auto-ingests audio files, transcribes them with OpenAI Whisper, and exposes a searchable REST API.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture Overview](#2-architecture-overview)
3. [Project Structure](#3-project-structure)
4. [Key Modules Explanation](#4-key-modules-explanation)
5. [Important Classes and Functions](#5-important-classes-and-functions)
6. [Data Structures](#6-data-structures)
7. [Dependencies](#7-dependencies)
8. [Setup and Installation](#8-setup-and-installation)
9. [Usage](#9-usage)
10. [Configuration](#10-configuration)
11. [Error Handling and Logging](#11-error-handling-and-logging)
12. [Possible Improvements](#12-possible-improvements)
13. [Summary](#13-summary)

---

## 1. Project Overview

### What is MeetRec?

MeetRec is a **self-hosted meeting transcription platform** designed for organizations that need to automatically transcribe, store, and search audio recordings of meetings (e.g., local government sessions, board meetings, town halls).

### What problem does it solve?

Organizations often generate large volumes of meeting recordings that are impossible to search through manually. MeetRec automates the full pipeline:

- **Ingest** audio files automatically (drop-folder model) or via API upload
- **Validate** files for format, size, duration, and integrity
- **Transcribe** speech to text using OpenAI Whisper (local, no cloud dependency)
- **Store** transcripts with per-sentence timestamps for audio synchronization
- **Search** across all transcripts using PostgreSQL full-text search
- **Audit** every access, view, search, and export for legal compliance

### Main Functionality

| Feature | Description |
|---|---|
| Automatic file ingestion | Drop an audio file into `/data/inbox` — it's processed automatically |
| API upload | Upload via `POST /api/v1/recordings/{id}/upload` |
| Speech-to-text | OpenAI Whisper (medium model, ~85% accuracy on Romanian) |
| Full-text search | PostgreSQL TSVECTOR + GIN index, returns snippets with highlighted terms |
| Transcript segments | Each sentence stored with `start_time` / `end_time` for audio sync |
| Language detection | Automatic detection from the first 30 seconds of audio |
| Diacritics correction | Post-processor normalizes Romanian diacritics (cedilla → comma-below) |
| Audit log | Every action (upload, view, search, delete, export) is recorded |
| Export | PDF, DOCX, TXT (via ReportLab and python-docx) |
| Retention policy | Configurable auto-deletion after N days |
| JWT authentication | HS256 JWT tokens, bcrypt password hashing |
| Monitoring | Grafana + Loki + Promtail centralized logging stack |

---

## 2. Architecture Overview

MeetRec is a **microservices system** orchestrated with Docker Compose. The three core Python services communicate through a PostgreSQL database and a Redis queue.

```
                        ┌─────────────────────────────────────┐
                        │          Docker Network              │
                        │                                      │
 Audio File             │  ┌─────────┐   LPUSH   ┌──────────┐ │
  (inbox)  ──────────▶  │  │  Ingest │──────────▶│  Redis   │ │
                        │  │ Service │           │  Queue   │ │
                        │  └────┬────┘           └────┬─────┘ │
                        │       │                     │BRPOP  │
                        │       │ INSERT              ▼       │
                        │       │         ┌───────────────┐   │
                        │  ┌────▼─────┐   │  STT Worker   │   │
  REST Client ────────▶ │  │PostgreSQL│◀──│  (Whisper)    │   │
   (Browser / API)      │  │   DB     │   └───────────────┘   │
         ▲              │  └────▲─────┘                       │
         │              │       │                             │
         │              │  ┌────┴─────┐                       │
         └──────────────│──│   API    │                       │
          (via Nginx)   │  │ FastAPI  │                       │
                        │  └──────────┘                       │
                        │                                      │
                        │  ┌──────────────────────────────┐   │
                        │  │  Grafana + Loki + Promtail   │   │
                        │  └──────────────────────────────┘   │
                        └─────────────────────────────────────┘
```

### Component Roles

| Component | Technology | Role |
|---|---|---|
| **API Service** | FastAPI + SQLAlchemy | REST API, business logic, JWT auth, audit |
| **Ingest Service** | watchdog + asyncpg | File system watcher, validator, queue publisher |
| **STT Worker** | OpenAI Whisper + asyncpg | Speech-to-text transcription engine |
| **PostgreSQL** | postgres:15-alpine | Primary data store (recordings, transcripts, audit) |
| **Redis** | redis:7-alpine | FIFO job queue between Ingest and STT Worker |
| **Nginx** | nginx:1.25-alpine | Reverse proxy, HTTPS termination, rate limiting |
| **Frontend** | React (not explored) | Web UI |
| **Audit-Retention** | Python service | Scheduled cleanup of expired recordings |
| **Grafana / Loki / Promtail** | Grafana stack | Log aggregation and dashboards |

### Data Flow

```
1. Audio file appears in /data/inbox/
       │
       ▼
2. Ingest Service detects file (inotify)
   ├── Validates: format, size, duration, SHA256 hash
   ├── Checks for duplicate (by hash in DB)
   ├── Moves to /data/processed/YYYY/MM/DD/{uuid}.ext
   ├── Creates rows in: recordings + transcripts (status=pending)
   └── Publishes job to Redis queue (LPUSH)
       │
       ▼
3. STT Worker picks up job (BRPOP)
   ├── Marks transcript → "processing"
   ├── Detects language (first 30s via Whisper)
   ├── Transcribes entire file (Whisper medium model)
   ├── Post-processes: fixes diacritics, normalizes whitespace
   └── Saves results to DB: bulk INSERT transcript_segments
       │                     UPDATE transcripts → "completed"
       │                     UPDATE recordings  → "completed"
       ▼
4. API serves results
   ├── GET /api/v1/recordings/{id}
   ├── GET /api/v1/transcripts/recording/{id}
   └── GET /api/v1/search?q=buget+2024
```

---

## 3. Project Structure

```
MeetRec/
│
├── docker-compose.yml          # Orchestrates all 10+ containers
├── .env.example                # Environment variable template
├── Makefile                    # Convenience commands (make start, make logs)
│
├── database/
│   ├── init.sql                # Full PostgreSQL schema with ENUMs, indexes, triggers
│   └── migrations/             # Placeholder for future Alembic migrations
│
├── services/
│   │
│   ├── api/                    # FastAPI REST backend
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── src/
│   │       ├── main.py         # App entry, lifespan, CORS, global error handler
│   │       ├── config.py       # Pydantic Settings (reads from .env)
│   │       ├── database.py     # SQLAlchemy async engine + session dependency
│   │       ├── models/
│   │       │   ├── base.py         # SQLAlchemy declarative Base
│   │       │   ├── recording.py    # Recording ORM model + enums
│   │       │   ├── transcript.py   # Transcript + TranscriptSegment ORM models
│   │       │   └── audit_log.py    # AuditLog + User ORM models
│   │       ├── routers/
│   │       │   ├── recordings.py   # CRUD endpoints: /api/v1/recordings
│   │       │   ├── transcript.py   # /api/v1/transcripts/recording/{id}
│   │       │   └── search.py       # /api/v1/search?q=...
│   │       ├── schemas/
│   │       │   └── recording.py    # All Pydantic request/response schemas
│   │       ├── services/
│   │       │   ├── recording_service.py  # Recording CRUD business logic
│   │       │   ├── transcript_service.py # Transcript retrieval + retry
│   │       │   └── search_service.py     # PostgreSQL FTS query logic
│   │       └── middleware/
│   │           ├── audit.py        # log_audit() helper function
│   │           └── auth.py         # JWT encode/decode, get_current_user dependency
│   │
│   ├── ingest/                 # File watcher and ingest pipeline
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── src/
│   │       ├── main.py         # Entry point: startup, signal handlers, shutdown
│   │       ├── config.py       # Pydantic Settings for ingest
│   │       ├── logger.py       # structlog setup
│   │       ├── watcher.py      # InboxWatcher + AudioFileHandler (watchdog)
│   │       ├── processor.py    # FileProcessor: orchestrates validate→store→db→publish
│   │       ├── validator.py    # AudioValidator: format, size, hash, mutagen metadata
│   │       ├── storage.py      # StorageManager: date-organized file placement
│   │       ├── publisher.py    # JobPublisher: LPUSH to Redis with retry
│   │       └── database.py     # DatabaseClient: asyncpg connection + recording insert
│   │
│   └── stt-worker/             # Whisper speech-to-text worker
│       ├── Dockerfile
│       ├── requirements.txt
│       └── src/
│           ├── main.py             # Entry point: load model, start consumer, SIGTERM
│           ├── config.py           # Pydantic Settings for stt-worker
│           ├── consumer.py         # JobConsumer: BRPOP loop, pipeline orchestration
│           ├── transcriber.py      # WhisperTranscriber: load model, transcribe (thread pool)
│           ├── language_detector.py# LanguageDetector: detect language from first 30s
│           ├── postprocessor.py    # PostProcessor: fix diacritics, normalize whitespace
│           └── uploader.py         # DatabaseUploader: asyncpg bulk insert results
│
├── monitoring/
│   ├── loki/loki-config.yaml       # Loki log aggregator config
│   └── promtail/promtail-config.yaml # Promtail log shipper config
│
├── nginx/                      # Nginx reverse proxy config (referenced, not shown)
├── frontend/                   # React frontend (referenced, not explored)
└── data/
    └── inbox/                  # Drop-folder for audio files (mounted as volume)
```

---

## 4. Key Modules Explanation

### 4.1 API Service — `services/api/src/`

The API is the **central hub** for all client interactions and for managing state transitions of recordings.

| Module | Purpose | Interacts With |
|---|---|---|
| `main.py` | FastAPI app factory, middleware, lifecycle | All routers |
| `config.py` | Typed settings from environment | All modules |
| `database.py` | Async SQLAlchemy engine, `get_db()` dependency | Services, routers |
| `models/` | ORM models (Recording, Transcript, AuditLog, User) | Services, DB |
| `schemas/` | Pydantic schemas for request/response validation | Routers |
| `routers/` | HTTP route handlers (thin layer, delegates to services) | Services, middleware |
| `services/` | Business logic (query building, file handling, Redis publish) | Models, Redis, filesystem |
| `middleware/audit.py` | Writes audit log entries via the current DB session | AuditLog model |
| `middleware/auth.py` | JWT generation/validation, user lookup, bcrypt hashing | User model |

### 4.2 Ingest Service — `services/ingest/src/`

A **background daemon** that watches `/data/inbox/` and triggers the full ingestion pipeline for any new audio file found.

| Module | Purpose |
|---|---|
| `main.py` | Async entry point; wires components, registers SIGTERM/SIGINT handlers |
| `watcher.py` | `InboxWatcher` wraps watchdog `Observer`; `AudioFileHandler` handles `on_created` / `on_moved` events. Waits for file stability before processing. |
| `processor.py` | `FileProcessor` — Facade pattern. Calls validator → storage → database → publisher in sequence with rollback on failure |
| `validator.py` | `AudioValidator` — validates extension, size, hash, duration using `mutagen` |
| `storage.py` | `StorageManager` — moves files to `/data/processed/YYYY/MM/DD/{uuid}.ext` |
| `publisher.py` | `JobPublisher` — serializes `TranscriptionJob` to JSON and `LPUSH`es to Redis with exponential-backoff retry |
| `database.py` | `DatabaseClient` — asyncpg-based; creates recording + transcript rows; checks duplicate by SHA256 hash |

### 4.3 STT Worker — `services/stt-worker/src/`

A **background worker** that consumes transcription jobs from Redis, runs Whisper inference in a thread pool, and writes results to PostgreSQL.

| Module | Purpose |
|---|---|
| `main.py` | Startup: connect DB → load model → start consumer. Handles SIGTERM gracefully |
| `consumer.py` | `JobConsumer` — BRPOP loop; orchestrates the 7-step pipeline per job |
| `transcriber.py` | `WhisperTranscriber` — wraps Whisper in `run_in_executor` to avoid blocking the async event loop |
| `language_detector.py` | `LanguageDetector` — uses the already-loaded Whisper model to detect language from the first 30 seconds |
| `postprocessor.py` | `PostProcessor` — fixes Romanian diacritics (cedilla→comma-below), normalizes whitespace |
| `uploader.py` | `DatabaseUploader` — asyncpg bulk INSERT for segments + UPDATE for transcript/recording status |
| `config.py` | Pydantic Settings; validates that `audio_storage_path` exists (read-only mount) |

---

## 5. Important Classes and Functions

### `RecordingService` (`services/api/src/services/recording_service.py`)

Central business logic for recordings. The router calls this; it never touches HTTP directly.

| Method | Description |
|---|---|
| `list_recordings()` | Paginated, filterable, sortable query using SQLAlchemy ORM. Counts before slicing. |
| `get_by_id()` | Fetches one recording; SQLAlchemy auto-loads the related transcript via `lazy="selectin"` |
| `create()` | Creates a `Recording` row and an associated `Transcript` row (status=pending) in one flush |
| `process_upload()` | Reads uploaded file bytes, computes SHA256, saves to disk, updates recording, publishes Redis job |
| `update()` | PATCH semantics: `model_dump(exclude_unset=True)` applies only the provided fields |
| `delete()` | Removes the physical file from disk + the DB row (CASCADE removes transcript + segments) |
| `_publish_job()` | Opens an async Redis connection, `LPUSH`es the job JSON, closes connection |

### `FileProcessor` (`services/ingest/src/processor.py`)

**Facade** that wires together four injected dependencies.

```
process(file_path)
  ├── Step 1: validator.validate(file_path)         → ValidationResult
  ├── Step 2: database.check_duplicate(hash)        → existing_id or None
  ├── Step 3: storage.store_file(metadata)          → stored_path
  ├── Step 4: database.create_recording(metadata)   → recording_id
  └── Step 5: publisher.publish_transcription_job() → bool
```

Errors in step 3 return `False` and leave the inbox file untouched. Errors in step 5 leave the recording in DB with status `queued` for a future retry — the file is not rolled back.

### `JobConsumer` (`services/stt-worker/src/consumer.py`)

Implements the main worker loop. Uses `redis.asyncio` (non-blocking `BRPOP`) so the asyncio event loop stays free while waiting for jobs.

**Per-job pipeline:**
```
_process_job(job)
  ├── Step 1: get_transcript_id(recording_id)
  ├── Step 2: mark_processing(transcript_id)           → DB status = 'processing'
  ├── Step 3: detector.detect(file_path)               → language code ("ro")
  ├── Step 4: transcriber.transcribe(file_path, lang)  → List[TranscriptSegment]
  ├── Step 5: postprocessor.process(segments)          → List[TranscriptSegment]
  ├── Step 6: _compute_metadata(segments)              → TranscriptMetadata
  └── Step 7: uploader.save_results(...)               → DB status = 'completed'
```

On any exception: `mark_failed()` is called with the error message. The worker **does not crash** — it continues to the next job.

### `WhisperTranscriber` (`services/stt-worker/src/transcriber.py`)

Wraps the synchronous Whisper library to be safe in an async context.

- **`load_model()`** — calls `whisper.load_model()` via `run_in_executor()` (blocking, 5–30 s)
- **`transcribe()`** — calls `_run_whisper_sync()` via `run_in_executor()` (blocking, minutes)
- **`_convert_segment()`** — converts Whisper's raw dict to `TranscriptSegment`; converts `avg_logprob` (log-probability) to a linear confidence score `[0.0, 1.0]` clamped for the `DECIMAL(4,3)` DB column

### `AudioValidator` (`services/ingest/src/validator.py`)

Applies "cheapest check first" strategy:

1. File exists and is a regular file
2. Extension is in the allowed set
3. File size is between 1 byte and 500 MB
4. SHA256 hash computed (streaming, 8 MB chunks — memory-efficient for large files)
5. `mutagen.File()` reads audio headers — extracts duration, sample rate, channels, bitrate
6. Duration must be between 5 seconds and 12 hours

### `SearchService` (`services/api/src/services/search_service.py`)

Executes a raw SQL query against the PostgreSQL full-text search index:

- Uses `plainto_tsquery('romanian', :query)` — accepts natural language (no operator syntax required)
- Ranks results by `ts_rank` (relevance score)
- Returns `ts_headline` — a text snippet with the matched term wrapped in `<b>...</b>`
- Filters on `transcripts.status = 'completed'` and `search_vector @@ tsquery`

### `log_audit()` (`services/api/src/middleware/audit.py`)

A simple async function called explicitly in each router after important operations. Extracts the real client IP from `X-Real-IP` / `X-Forwarded-For` headers (Nginx sets these). The audit log entry is added to the **same DB session** so it's committed atomically with the business operation.

### `DatabaseUploader.save_results()` (`services/stt-worker/src/uploader.py`)

Uses `asyncpg.executemany()` for bulk INSERT of transcript segments — typically 60× faster than individual `execute()` calls. All three operations (INSERT segments, UPDATE transcript, UPDATE recording) happen inside a single transaction. Uses `ON CONFLICT DO NOTHING` for idempotency (safe to retry if the worker crashes mid-save).

---

## 6. Data Structures

### Database Schema

```
recordings (1)──────────────────(1) transcripts (1)────────(N) transcript_segments
     │                                    │
     │                                    └── search_vector TSVECTOR
     └── status: uploaded → validating → queued → transcribing → completed / failed
```

### `AudioMetadata` (Python dataclass — Ingest Service)

```python
@dataclass
class AudioMetadata:
    filename: str
    file_path: Path
    file_size_bytes: int
    file_hash_sha256: str       # 64-char hex string
    audio_format: str           # "mp3", "wav", etc.
    duration_seconds: int
    sample_rate_hz: Optional[int]
    channels: Optional[int]
    bitrate_kbps: Optional[int]
```

Produced by `AudioValidator.validate()` and passed through the entire ingest pipeline (to `StorageManager`, `DatabaseClient`, `JobPublisher`).

### `TranscriptSegment` (Python dataclass — STT Worker)

```python
@dataclass
class TranscriptSegment:
    segment_index: int       # 0-based order
    start_time: float        # seconds from start of audio, e.g. 12.500
    end_time: float          # e.g. 17.320
    text: str                # "Bună ziua, doamnă primar."
    confidence: float        # 0.0–1.0 (from Whisper avg_logprob)
    language: str            # "ro", "en", etc.
```

### `TranscriptionJob` (published to Redis)

```json
{
  "recording_id": "a1b2c3d4-...",
  "file_path": "/data/processed/2024/01/15/a1b2c3d4.mp3",
  "audio_format": "mp3",
  "duration_seconds": 3600,
  "language_hint": "ro",
  "priority": 0,
  "created_at": "2024-01-15T10:00:00+00:00",
  "estimated_processing_time_minutes": 120
}
```

### Status Enumerations

**Recording Status** (linear progression):
```
uploaded → validating → queued → transcribing → completed
                                              → failed
                                              → archived
```

**Transcript Status:**
```
pending → processing → completed
                    → failed
                    → cancelled
```

### Response Schemas (Pydantic)

| Schema | Used for |
|---|---|
| `RecordingCreate` | `POST /recordings` — validates title, meeting_date (not future), participants |
| `RecordingUpdate` | `PATCH /recordings/{id}` — all fields optional (PATCH semantics) |
| `RecordingResponse` | Full recording detail. Excludes `file_path` (security) |
| `RecordingListItem` | Compact list item with transcript status |
| `PaginatedRecordings` | Wraps list + total + page + pages |
| `TranscriptResponse` | Full transcript with `List[SegmentResponse]` and `full_text` |
| `SearchResult` | One hit: timestamps, text snippet, `headline` with `<b>` tags, `rank` |
| `SearchResponse` | Wraps results + `total_results` + `search_time_ms` |
| `UploadResponse` | Returned on `POST /{id}/upload` — includes estimated processing time |

---

## 7. Dependencies

### API Service

| Library | Version | Purpose |
|---|---|---|
| `fastapi` | 0.111.0 | Async REST framework with automatic OpenAPI docs |
| `uvicorn[standard]` | 0.29.0 | ASGI server; `standard` adds hot-reload support |
| `pydantic` | 2.7.1 | Data validation and serialization |
| `pydantic-settings` | 2.2.1 | Loads `Settings` from `.env` and environment variables |
| `sqlalchemy` | 2.0.30 | Async ORM (declarative, typed with `Mapped[]`) |
| `asyncpg` | 0.29.0 | Fast async PostgreSQL driver |
| `alembic` | 1.13.1 | Database migrations (not yet used in production) |
| `python-jose[cryptography]` | 3.3.0 | JWT token generation and verification (HS256) |
| `passlib[bcrypt]` | 1.7.4 | Password hashing with bcrypt |
| `redis` | 5.0.4 | Async Redis client (for publishing transcription jobs) |
| `python-multipart` | 0.0.9 | Enables file upload parsing in FastAPI |
| `aiofiles` | 23.2.1 | Async file I/O |
| `reportlab` | 4.1.0 | PDF generation for transcript export |
| `python-docx` | 1.1.0 | DOCX generation for transcript export |
| `structlog` | 24.2.0 | Structured JSON logging |
| `tenacity` | 8.3.0 | Retry decorator with exponential backoff |
| `httpx` | 0.27.0 | Async HTTP client for inter-service calls |

### Ingest Service

| Library | Version | Purpose |
|---|---|---|
| `watchdog` | 3.0.0 | OS-native file system event monitoring (inotify on Linux) |
| `mutagen` | 1.47.0 | Audio metadata extraction (format, duration, sample rate) without full decoding |
| `pydub` | 0.25.1 | Additional audio file validation (wraps ffmpeg) |
| `asyncpg` | 0.29.0 | Async PostgreSQL driver |
| `redis` | 5.0.1 | Redis client for LPUSH |
| `tenacity` | 8.2.3 | Retry for Redis publish |
| `structlog` | 24.1.0 | JSON logging |

### STT Worker

| Library | Version | Purpose |
|---|---|---|
| `openai-whisper` | latest | Core STT engine — multilingual transformer model |
| `numpy` | <2.0 | Required by PyTorch/Whisper (numpy 2.x incompatible with torch 2.1.0) |
| `torch` | 2.1.0+cpu | Deep learning runtime (CPU-only build for servers without GPU) |
| `asyncpg` | 0.29.0 | Async PostgreSQL for bulk INSERT of segments |
| `redis` | 5.0.1 | Async Redis client (`redis.asyncio`) for BRPOP |
| `structlog` | 24.1.0 | JSON logging |
| `tenacity` | 8.2.3 | Retry for connection resilience |

---

## 8. Setup and Installation

### Prerequisites

- Docker ≥ 24.0
- Docker Compose v2 (`docker compose` command)
- 6 GB free disk space (Whisper medium model: ~1.5 GB, Docker images: ~3-5 GB)
- 6 GB RAM minimum (Whisper medium needs ~5 GB during transcription)

### Step-by-step Installation

**1. Clone the repository**
```bash
git clone <repository-url>
cd MeetRec
```

**2. Create environment file**
```bash
cp .env.example .env
```

**3. Edit `.env` with your values** (see [Section 10](#10-configuration))

```bash
# Required — set a strong secret
JWT_SECRET_KEY=your-very-secret-key-at-least-32-chars

# Required — PostgreSQL credentials
POSTGRES_USER=meetrec
POSTGRES_PASSWORD=strongpassword123
POSTGRES_DB=meetrec_db
DATABASE_URL=postgresql+asyncpg://meetrec:strongpassword123@postgres:5432/meetrec_db
```

**4. Create the inbox directory**
```bash
mkdir -p data/inbox
```

**5. Build and start all services**
```bash
docker compose up --build -d
```

This will:
- Build Docker images for `api`, `ingest`, `stt-worker`
- Pull images for PostgreSQL, Redis, Nginx, Grafana, Loki, Promtail
- Run `database/init.sql` to create the schema (first start only)
- Download the Whisper medium model (~1.5 GB) on first STT Worker startup

**6. Verify services are healthy**
```bash
docker compose ps
# All services should show "healthy" or "running"

curl http://localhost:8080/health
# {"status":"healthy","service":"meeting-transcriber-api","version":"1.0.0","environment":"development"}
```

**7. Open API documentation** (development mode only)
```
http://localhost:8080/docs
```

---

## 9. Usage

### Automatic Ingestion (Drop-Folder)

Simply copy a supported audio file into the inbox directory:

```bash
cp /path/to/meeting.mp3 data/inbox/
```

The Ingest Service detects the file within seconds, validates it, moves it to `/data/processed/`, creates DB records, and dispatches a transcription job. Monitor progress:

```bash
docker compose logs -f ingest stt-worker
```

### REST API

All endpoints are prefixed with `/api/v1`.

**Create a recording (metadata only):**
```bash
curl -X POST http://localhost:8080/api/v1/recordings/ \
  -H "Content-Type: application/json" \
  -d '{
    "title": "City Council Meeting — January 15 2024",
    "meeting_date": "2024-01-15",
    "location": "Main Hall",
    "participants": ["Ion Ionescu", "Maria Pop"]
  }'
```

**Upload audio file:**
```bash
curl -X POST http://localhost:8080/api/v1/recordings/{id}/upload \
  -F "file=@/path/to/meeting.mp3"
```

**List recordings:**
```bash
# With pagination and status filter
curl "http://localhost:8080/api/v1/recordings/?page=1&page_size=20&status=completed"

# Search by title
curl "http://localhost:8080/api/v1/recordings/?search=council"
```

**Get recording details:**
```bash
curl http://localhost:8080/api/v1/recordings/{id}
```

**Get transcript with segments:**
```bash
curl http://localhost:8080/api/v1/transcripts/recording/{id}
```

**Full-text search:**
```bash
curl "http://localhost:8080/api/v1/search?q=buget+2024"
curl "http://localhost:8080/api/v1/search?q=vote&language=en&limit=10"
```

**Retry failed transcription:**
```bash
curl -X POST http://localhost:8080/api/v1/transcripts/recording/{id}/retry
```

**Update recording metadata:**
```bash
curl -X PATCH http://localhost:8080/api/v1/recordings/{id} \
  -H "Content-Type: application/json" \
  -d '{"title": "Updated Title"}'
```

**Delete a recording:**
```bash
curl -X DELETE http://localhost:8080/api/v1/recordings/{id}
# Returns 204 No Content on success
```

### Monitoring

```bash
# View real-time logs
docker compose logs -f

# Access Grafana dashboards
open http://localhost:3000
# Default credentials: admin / (value of GRAFANA_ADMIN_PASSWORD in .env)
```

---

## 10. Configuration

All configuration is managed through environment variables loaded from a `.env` file. The Pydantic `Settings` classes in each service validate types at startup — if a required variable is missing, the service **refuses to start** with a clear error message.

### Core Variables (`.env`)

| Variable | Default | Required | Description |
|---|---|---|---|
| `DATABASE_URL` | — | ✅ | PostgreSQL connection string. Format: `postgresql+asyncpg://user:pass@host:port/db` |
| `POSTGRES_USER` | — | ✅ | PostgreSQL username (used by the postgres container) |
| `POSTGRES_PASSWORD` | — | ✅ | PostgreSQL password |
| `POSTGRES_DB` | — | ✅ | PostgreSQL database name |
| `JWT_SECRET_KEY` | — | ✅ | HS256 signing key (min. 32 chars recommended) |
| `REDIS_URL` | `redis://redis:6379` | | Redis connection URL |
| `REDIS_TRANSCRIPTION_QUEUE` | `transcription_jobs` | | Redis list name for the job queue |
| `APP_ENV` | `development` | | `development` enables `/docs`, permissive CORS |
| `LOG_LEVEL` | `INFO` | | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` |

### Storage Variables

| Variable | Default | Description |
|---|---|---|
| `INBOX_PATH` | `/data/inbox` | Directory watched by Ingest Service |
| `AUDIO_STORAGE_PATH` | `/data/processed` | Organized storage for validated audio files |
| `EXPORT_PATH` | `/data/exports` | Output directory for PDF/DOCX exports |
| `MAX_FILE_SIZE_BYTES` | `524288000` | 500 MB upload limit |

### Auth Variables

| Variable | Default | Description |
|---|---|---|
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `JWT_EXPIRE_MINUTES` | `480` | Token lifetime (8 hours) |

### Whisper Variables

| Variable | Default | Description |
|---|---|---|
| `WHISPER_MODEL` | `medium` | Model size: `tiny`, `base`, `small`, `medium`, `large` |
| `WHISPER_PRIMARY_LANGUAGE` | `ro` | Default language hint passed to Whisper |
| `WHISPER_MODEL_PATH` | `/app/models` | Persistent directory for cached model files |

### Retention Variables

| Variable | Default | Description |
|---|---|---|
| `RETENTION_DAYS` | `1095` | 3 years — how long to keep recordings |
| `AUDIT_LOG_RETENTION_DAYS` | (service default) | How long to keep audit log entries |

### Grafana

| Variable | Default | Description |
|---|---|---|
| `GRAFANA_ADMIN_PASSWORD` | — | Admin password for Grafana UI |
| `GRAFANA_PORT` | `3000` | Host port for Grafana |
| `NGINX_HTTPS_PORT` | `443` | Host port for Nginx HTTPS |

---

## 11. Error Handling and Logging

### Error Handling Strategy

**Ingest Service:**
- Files that fail validation are moved to `/data/inbox/errors/` for manual inspection (not deleted)
- Duplicate files (same SHA256 hash) are silently deleted from inbox
- If storage fails (step 3), the function returns `False` and leaves the inbox file in place
- If DB fails (step 4), the stored file is deleted (manual rollback) to maintain consistency
- If Redis publish fails (step 5), the recording stays in DB with status `queued` — a recovery job can re-publish later
- Redis publish retries with exponential backoff (1s → 2s → 4s, max 3 attempts) using `tenacity`

**STT Worker:**
- Any exception during job processing triggers `mark_failed()` — records the error message in `transcripts.error_message`
- The worker **never stops** due to a single job failure — it logs the error and continues with the next job
- If Redis is temporarily unavailable, `_poll_once()` sleeps 5 seconds and retries (avoids log spam)
- Graceful shutdown: `consumer.stop()` sets `_running = False`; the current transcription is allowed to finish before the process exits

**API Service:**
- A global `@app.exception_handler(Exception)` catches any unhandled exception and returns `500` with a generic message (no stack trace exposed to the client)
- `HTTPException` is used for expected errors (404 not found, 400 bad request, 401 unauthorized, 403 forbidden)
- DB session in `get_db()` auto-commits on success and auto-rollbacks on exception
- Audit log entries are written in the same transaction as the business operation — either both succeed or both fail

### Logging

All services use **`structlog`** with JSON output format:

```json
{
  "timestamp": "2024-01-15T10:30:00+00:00",
  "level": "info",
  "event": "job_completed",
  "recording_id": "a1b2-...",
  "segments": 142,
  "words": 2341,
  "processing_sec": 312
}
```

Structured logs (key=value fields, not free-form strings) allow **Loki / Grafana** to filter and aggregate by any field:
- `event = "job_failed"` → alert on transcription failures
- `event = "file_rejected"` → monitor for bad file uploads
- `event = "redis_brpop_error"` → alert on queue connectivity issues

Log levels used:
- `DEBUG` — detailed query info (SQL echo in development mode)
- `INFO` — normal flow events (file detected, job started, job completed)
- `WARNING` — recoverable issues (duplicate file, language override, file stability timeout)
- `ERROR` — failures requiring attention (DB error, storage failure, unhandled exception)

---

## 12. Possible Improvements

### Architecture

1. **Message broker durability** — Redis `BRPOP` is not truly reliable: if the worker crashes between `BRPOP` and `mark_processing`, the job is lost. Consider using Redis Streams (with consumer groups and `XACK`) or a dedicated message broker like RabbitMQ for at-least-once delivery guarantees.

2. **Worker concurrency** — The STT Worker processes one job at a time (`stt_worker_concurrency = 1`). The `config.py` already includes this setting. Scale horizontally by running multiple `stt-worker` containers (Redis BRPOP distributes jobs automatically between consumers).

3. **Speaker diarization** — The `speaker_id` column exists in `transcript_segments` but is never populated. Integrate `pyannote-audio` (speaker diarization) to identify who speaks each segment.

4. **GPU support** — The Docker Compose file includes commented-out GPU configuration. With an NVIDIA GPU and the CUDA-enabled Whisper build, transcription would be 10–20× faster.

5. **Export service** — Export functionality (PDF, DOCX) is referenced in `requirements.txt` but not yet implemented in the routers.

### Code Quality

6. **Authentication enforcement** — The `get_current_user` dependency exists in `middleware/auth.py` but is **not applied** to any router endpoint. All API endpoints are currently unauthenticated. Apply `Depends(get_current_user)` to routers as needed.

7. **Login endpoint** — There is no `POST /auth/login` endpoint implemented yet. The `authenticate_user()` and `create_access_token()` helpers are ready in `middleware/auth.py` but no router registers them.

8. **Alembic migrations** — The `database/migrations/` directory is empty. All schema is defined in `init.sql` (runs once). For production use, introduce Alembic to manage schema evolution safely.

9. **Redis connection reuse** — `RecordingService._publish_job()` opens and closes a Redis connection on every upload. This should use a shared connection pool (injectable via FastAPI dependency) for efficiency.

10. **`ingest/database.py`** — This module is referenced in the ingest service but was not fully explored. Ensure it handles the connection lifecycle properly (connection pooling, reconnection on failure).

### Operational

11. **Health endpoints** — The API has `/health`. The Ingest Service and STT Worker have no health endpoints — Docker can only rely on process liveness. Add simple TCP or HTTP health probes.

12. **Metrics** — No Prometheus metrics are exported. Expose metrics (queue depth, transcription duration, failure rate) for better observability beyond log scanning.

13. **File deduplication race condition** — Between `check_duplicate()` and `create_recording()`, a second identical file could pass the duplicate check. Add a database-level `UNIQUE` constraint on `file_hash_sha256` (it already exists!) and handle the `UniqueViolation` exception instead of doing an application-level check.

---

## 13. Summary

MeetRec is a well-structured **event-driven microservices system** for automated meeting audio transcription. Its core design decisions are:

- **Drop-folder ingest** via OS-native file system events (`inotify`) — zero polling overhead
- **Redis FIFO queue** decouples ingest from transcription — ingest is fast (milliseconds), transcription is slow (minutes)
- **OpenAI Whisper** runs entirely locally — no cloud API keys or data privacy concerns
- **PostgreSQL full-text search** with `TSVECTOR` and GIN index — sub-millisecond search across thousands of transcripts
- **`asyncio.run_in_executor()`** isolates the blocking Whisper CPU work from the async event loop
- **Fail-fast configuration** — Pydantic Settings validates all environment variables at startup; missing secrets cause immediate startup failure
- **Comprehensive audit trail** — every view, search, upload, delete is recorded for legal compliance
- **Structured JSON logging** — all services emit machine-readable logs consumed by Grafana Loki

The system is production-ready in its data pipeline (ingest → validate → store → transcribe → search) but requires additional work in **authentication enforcement**, **login endpoint**, and **Alembic migrations** before deployment in a public-facing environment.

---
