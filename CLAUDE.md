# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MeetRec is a self-hosted meeting transcription platform with a microservices architecture. The system automatically ingests audio files, transcribes them with Whisper STT, indexes transcripts for full-text and semantic search, and exposes a REST API consumed by a React frontend.

## Common Commands

All day-to-day operations go through `make` (wraps `docker compose`):

```bash
make setup           # First-time setup: creates .env from .env.example, creates data folders
make build           # Rebuild Docker images after Dockerfile/dependency changes
make start           # Start all 9 services
make start-core      # Start only postgres, redis, api, frontend, nginx
make stop            # Stop services
make logs            # Tail logs for all services
make logs-api        # Tail logs for a specific service (replace 'api' with any service name)
make ps              # Show service health status

make test            # Run all backend tests (pytest for api + ingest + stt-worker, inside Docker)
make frontend-test   # Run frontend tests (Vitest, inside Docker)

make db-shell        # psql into PostgreSQL
make redis-cli       # Redis interactive shell
make redis-queue     # Check transcription queue length
make api-shell       # bash inside the api container
make stt-shell       # bash inside the stt-worker container
make audit-shell     # bash inside the audit-retention container
make clean-all       # WARNING: destroys all containers AND volumes (data loss)
```

### Running tests directly

```bash
# Backend — run inside each Docker container (tests live in tests/ under each service)
docker compose exec api pytest tests/ -v
docker compose exec api pytest tests/test_recordings.py -v   # single file
docker compose exec api pytest tests/ -k "test_health" -v    # single test
docker compose exec ingest pytest tests/ -v
docker compose exec stt-worker pytest tests/ -v

# Frontend
cd frontend
npm run test            # single run
npm run test:watch      # watch mode
npm run test:coverage   # with coverage report
```

### Frontend dev outside Docker

```bash
cd frontend
npm install
npm run dev     # Vite dev server (needs API accessible at configured URL)
npm run build   # TypeScript compile + Vite bundle
```

## Architecture

### Services

| Service | Dir | Port | Purpose |
|---|---|---|---|
| **api** | `services/api/` | 8080 | FastAPI REST API — auth, recordings, transcripts, search, export, audit, users |
| **ingest** | `services/ingest/` | — | Watches `/data/inbox/`, validates audio, pushes jobs to Redis queue |
| **stt-worker** | `services/stt-worker/` | — | Consumes Redis queue, runs Whisper, stores transcript segments |
| **search-indexer** | `services/search-indexer/` | 8001 | Generates sentence-transformers embeddings on PostgreSQL NOTIFY |
| **audit-retention** | `services/audit-retention/` | — | APScheduler nightly job for GDPR-compliant auto-deletion |
| **frontend** | `frontend/` | 3000 | React 18 SPA (served via Nginx) |
| **postgres** | — | 5432 | PostgreSQL 15 + pgvector |
| **redis** | — | 6379 | Job queue (`transcription_jobs` key) |
| **nginx** | `nginx/` | 80/443 | Reverse proxy: `/api/` → api, `/` → frontend |

### Data Flow

1. Audio file dropped into `/data/inbox/` → **ingest** detects it, validates format/size, SHA-256 dedup, creates `Recording` record, pushes job ID to Redis.
2. **stt-worker** pops job from Redis, runs Whisper `medium` model, writes segments to `transcripts` table, updates `Recording.status` → `completed`.
3. PostgreSQL NOTIFY triggers **search-indexer** to generate 384-dim multilingual embeddings stored in pgvector.
4. **api** serves all reads/writes to the **frontend** through JWT-authenticated REST endpoints.

### Multi-Segment Sessions

Long meetings can be split across multiple audio files using a shared `session_id`. The first upload with a given `session_id` creates the primary `Recording`; subsequent uploads attach additional rows to `recording_audio_segments`. The **ingest** `session_watcher.py` monitors open sessions and triggers dispatch once `POST /inbox/session/{id}/complete` is called (or on timeout). **stt-worker** concatenates all segments before transcription via `audio_assembler.py`.

### API Service Structure (`services/api/src/`)

- `main.py` — FastAPI app init, CORS, rate limiting (slowapi), router registration under `/api/v1`
- `config.py` — Pydantic settings from `.env`; validates JWT secret length
- `database.py` — Async SQLAlchemy engine, `async_sessionmaker`, Alembic migrations run at startup
- `routers/` — One file per resource: `auth`, `inbox`, `recordings`, `transcript`, `search`, `export`, `audit`, `users`
- `models/` — SQLAlchemy ORM: `recording.py`, `transcript.py`, `audit_log.py`
- `services/` — Business logic: `recording_service`, `search_service`, `transcript_service`, `user_service`
- `middleware/auth.py` — JWT validation, `@requires_auth` decorator, RBAC (`admin`, `operator`, `participant`)
- `middleware/audit.py` — Auto-logs all mutations to `audit_logs` table

### Frontend Structure (`frontend/src/`)

- `pages/` — Route-level components (LoginPage, RecordingsListPage, RecordingDetailPage, SearchPage, AdminPage, etc.)
- `components/` — Feature components (`AudioPlayer`, `TranscriptViewer`, `ParticipantLinker`) and `ui/` kit (Spinner, Skeleton, StatusBadge, Pagination, etc.)
- `api/` — Axios client (`client.ts` adds JWT interceptor) + one file per domain (`recordings`, `search`, `transcripts`, `users`, `auditLogs`, `auth`)
- `contexts/` — `AuthContext.tsx` (global JWT state), `ToastContext.tsx`
- `lib/` — `cn.ts` (clsx wrapper), `formatTime.ts`
- `test/` — Vitest + Testing Library tests

### Ingest Service (`services/ingest/src/`)

- `watcher.py` — watchdog filesystem monitor for `/data/inbox/`
- `processor.py` — validates, deduplicates (SHA-256), writes `Recording` to DB
- `publisher.py` — pushes job IDs to Redis `transcription_jobs` queue
- `session_watcher.py` — monitors open multi-segment sessions; triggers completion
- `validator.py` / `storage.py` — audio format validation and file management

### STT Worker (`services/stt-worker/src/`)

- `consumer.py` — Redis queue consumer loop
- `transcriber.py` — wraps Whisper inference
- `audio_assembler.py` — concatenates multi-segment audio before transcription
- `language_detector.py` — auto-detects language when `WHISPER_PRIMARY_LANGUAGE` is unset
- `postprocessor.py` — normalizes Whisper output before storage
- `uploader.py` — writes transcript segments to PostgreSQL

### Database Schema

Defined in `database/init.sql`. Key tables: `users`, `recordings`, `recording_audio_segments` (multi-segment support), `transcripts`, `audit_logs`, plus pgvector extension for semantic search. Alembic migrations live in `services/api/alembic/versions/` and run automatically on API container startup.

## RBAC

Three roles: `admin` (full access + user management), `operator` (upload + manage own recordings), `participant` (read-only access to recordings they've been explicitly granted). Access control is enforced in `middleware/auth.py` and per-recording in `routers/recordings.py`.

## Configuration

Copy `.env.example` to `.env` before first run. Key variables:

- `JWT_SECRET_KEY` — must be ≥32 chars; generate with `python -c "import secrets; print(secrets.token_hex(32))"`
- `WHISPER_MODEL` — `tiny/base/small/medium/large`; default `medium`
- `WHISPER_PRIMARY_LANGUAGE` — default `ro` (Romanian)
- `RETENTION_DAYS` — auto-delete recordings after N days (default 3 years)
- `MAX_FILE_SIZE_BYTES` — default 500 MB

## Key Constraints

- Nginx is configured with `client_max_body_size 600M` — audio uploads must stay under this.
- STT Worker uses CPU-only torch by default; GPU support requires uncommenting the alternative torch index in `services/stt-worker/Dockerfile`.
- The `search-indexer` listens for PostgreSQL `NOTIFY` events — it must be running for semantic search to work on new recordings.
- Alembic migrations run automatically when the API container starts; never apply them manually against the production DB without understanding the migration state.
