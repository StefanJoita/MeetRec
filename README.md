<div align="center">

# 🎙 MeetRec

**Self-hosted meeting transcription platform — private, fast, and production-ready.**

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?style=flat-square&logo=typescript&logoColor=white)](https://typescriptlang.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-4169E1?style=flat-square&logo=postgresql&logoColor=white)](https://postgresql.org)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docker.com)
[![License](https://img.shields.io/badge/License-Proprietary-red?style=flat-square)](LICENSE)

*Drop an audio file. Get a searchable, exportable transcript. Everything runs on your infrastructure — no cloud, no subscriptions, no data leaving your premises.*

</div>

---

## What is MeetRec?

MeetRec is a fully self-hosted platform that automatically transcribes meeting recordings using **OpenAI Whisper** running locally. It provides a clean web interface for browsing, searching, and exporting transcripts, with a complete REST API for integration with other tools.

**Key principle:** audio never leaves your server. Transcription happens on-premise using Whisper — no third-party API calls, no data sent to the cloud.

---

## Features

| | Feature | Details |
|---|---|---|
| 🤖 | **Auto-transcription** | Drop audio in `/data/inbox` — transcription starts automatically |
| 🌐 | **Web upload** | Drag-and-drop interface or `POST /api/v1/inbox/upload` |
| 🎯 | **~85% accuracy** | Whisper `medium` model, optimized for Romanian |
| 🔍 | **Full-text search** | PostgreSQL `TSVECTOR` + GIN index, highlighted snippets |
| 🧠 | **Semantic search** | pgvector + sentence embeddings for meaning-based queries |
| 📄 | **Export** | Download transcripts as PDF, DOCX, or plain TXT |
| 🔐 | **Authentication** | JWT (HS256), bcrypt passwords, role-based access (admin/user) |
| 📋 | **Audit log** | Every action logged — upload, view, search, export, delete |
| 🗑️ | **Auto-retention** | Configurable auto-delete after N days (GDPR-friendly) |
| ⚡ | **Rate limiting** | Brute-force protection on login, throttling on search/export |
| 🎵 | **Synced player** | Audio player synchronized with transcript segments in real time |

---

## Architecture

```
Browser / Drop-folder
        │
        ▼
  POST /inbox/upload          cp meeting.mp3 data/inbox/
        │                              │
        ▼                              ▼
      API ────── writes ──────► /data/inbox/
                                       │
                               Ingest Service
                               (validate: format, size,
                                duration, SHA-256 dedup)
                                       │
                                       ▼
                                 Redis Queue
                                       │
                               STT Worker (Whisper)
                               (transcribe → segments
                                → full-text vectors)
                                       │
                                 PostgreSQL DB ◄─── Search Indexer
                                       ▲             (pgvector embeddings)
                                   FastAPI
                               (CRUD · search · export)
                                       ▲
                               Nginx ◄─── React SPA
```

**Golden rule:** Ingest Service is the **only** entry point for audio. It performs all validations. The API never touches audio files directly.

### Services

| Service | Technology | Role |
|---|---|---|
| **API** | FastAPI + SQLAlchemy async | REST endpoints, business logic |
| **Ingest** | Python watchdog + asyncpg | File detection, validation, queuing |
| **STT Worker** | OpenAI Whisper + asyncpg | Speech-to-text transcription |
| **Search Indexer** | Sentence Transformers + pgvector | Semantic embedding generation |
| **Audit Retention** | APScheduler | Scheduled cleanup, GDPR retention |
| **Frontend** | React 18 + Vite + TailwindCSS | Web interface |
| **DB** | PostgreSQL 15 + pgvector | Storage, full-text + vector search |
| **Queue** | Redis 7 | Job queue between Ingest and STT Worker |
| **Proxy** | Nginx 1.25 | Reverse proxy, static files |

---

## Quick Start

**Requirements:** Docker ≥ 24.0, Docker Compose v2, 6 GB RAM, 6 GB disk space.

```bash
# 1. Clone the repository
git clone https://github.com/StefanJoita/MeetRec.git
cd MeetRec

# 2. Set up environment variables
cp .env.example .env
# Edit .env — set JWT_SECRET_KEY and POSTGRES_PASSWORD

# 3. Generate a secure JWT secret
python -c "import secrets; print(secrets.token_hex(32))"
# Paste the output as JWT_SECRET_KEY in .env

# 4. Create data directories
mkdir -p data/inbox data/processed data/exports

# 5. Start all services
docker compose up --build -d

# 6. Verify everything is running
curl http://localhost:8080/health
# → {"status": "healthy", "services": {...}}
```

> **First startup:** Whisper `medium` model (~1.5 GB) will be downloaded automatically. This takes a few minutes on first run only.

**Web UI:** `http://localhost`
**API docs:** `http://localhost:8080/docs` *(development mode only)*

---

## Usage

### Drop-folder (simplest)

```bash
cp meeting.mp3 data/inbox/
# Ingest detects the file, validates it, and queues it for transcription
docker compose logs -f ingest stt-worker
```

### Web Interface

1. Open `http://localhost` and log in
2. Click **New Recording** → drag-and-drop your audio file
3. Wait for transcription (progress shown in real time)
4. Click on any transcript segment to jump to that moment in the audio
5. Use the **Search** page for full-text or semantic queries
6. Export to PDF/DOCX/TXT from the recording detail page

### REST API

```bash
# Authenticate
TOKEN=$(curl -s -X POST http://localhost:8080/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "your-password"}' \
  | jq -r '.access_token')

# Upload audio
curl -X POST http://localhost:8080/api/v1/inbox/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@meeting.mp3"
# → 202 Accepted

# List recordings
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8080/api/v1/recordings?page=1&page_size=20"

# Full-text search
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8080/api/v1/search?q=budget+2024"

# Export as PDF
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8080/api/v1/export/{id}?format=pdf" \
  --output transcript.pdf
```

Full API reference available at `/docs` when running in development mode.

---

## Configuration

All settings live in `.env`. Copy `.env.example` to get started.

### Required

| Variable | Description |
|---|---|
| `JWT_SECRET_KEY` | JWT signing key — **minimum 32 characters, cryptographically random** |
| `POSTGRES_PASSWORD` | PostgreSQL password |
| `DATABASE_URL` | `postgresql+asyncpg://meetrec:pass@postgres:5432/meetrec_db` |

### Optional

| Variable | Default | Description |
|---|---|---|
| `WHISPER_MODEL` | `medium` | Model size: `tiny` / `base` / `small` / `medium` / `large` |
| `RETENTION_DAYS` | `1095` | Days to keep recordings (default: 3 years) |
| `APP_ENV` | `development` | Set to `production` to disable `/docs` and restrict CORS |
| `MAX_FILE_SIZE_BYTES` | `524288000` | Max upload size (default: 500 MB) |
| `SEARCH_INDEXER_ENABLED` | `true` | Enable semantic search indexing |

---

## Security

MeetRec is designed with security in mind:

- **JWT authentication** with configurable expiry and forced password change on first login
- **bcrypt** password hashing (cost factor 12)
- **Rate limiting** via `slowapi` — 5 req/min on login, 20 req/hour on export
- **Path traversal protection** on all file operations (validated with `pathlib.Path.resolve()`)
- **Audit logging** — every user action is recorded with IP, timestamp, and user ID
- **Input validation** — file type verified by magic bytes, not just extension
- **CORS** restricted to explicit origins in production

> **Important:** Set `APP_ENV=production` in production. Never use `APP_ENV=development` with public-facing deployments.

---

## Project Structure

```
MeetRec/
├── services/
│   ├── api/                  # FastAPI application
│   │   ├── src/
│   │   │   ├── routers/      # auth, recordings, search, export, users
│   │   │   ├── services/     # business logic
│   │   │   ├── models/       # SQLAlchemy models
│   │   │   └── schemas/      # Pydantic schemas
│   │   └── tests/
│   ├── ingest/               # File watcher & validator
│   ├── stt-worker/           # Whisper transcription worker
│   ├── search-indexer/       # pgvector embedding service
│   └── audit-retention/      # Scheduled cleanup service
├── frontend/
│   └── src/
│       ├── pages/            # Login, Recordings, Search, Admin
│       ├── components/       # AudioPlayer, TranscriptViewer, ...
│       ├── api/              # Typed API client
│       └── contexts/         # Auth, Toast
├── database/
│   ├── init.sql              # Schema
│   └── migrations/           # SQL migrations
├── docker-compose.yml
└── .env.example
```

---

## Implementation Status

| Component | Status | Notes |
|---|---|---|
| Ingest Service | ✅ Complete | Validation: format, size, duration, SHA-256 dedup |
| STT Worker | ✅ Complete | Whisper medium, retry logic, async processing |
| API — auth, CRUD, search, export, audit | ✅ Complete | Rate limiting, JWT, role-based access |
| Frontend | ✅ Complete | Upload, list, detail, search, admin panel |
| Search Indexer | ✅ Complete | pgvector embeddings + PostgreSQL LISTEN/NOTIFY |
| Audit Retention | ✅ Complete | APScheduler, GDPR-compliant auto-delete |
| Database schema + migrations | ✅ Complete | GIN index, HNSW vector index |
| Full-text search | ✅ Complete | TSVECTOR + GIN, Romanian language support |
| Semantic search | ✅ Complete | Sentence Transformers + pgvector |
| Virtual scrolling | ✅ Complete | @tanstack/react-virtual, 1000+ segments |
| Error boundaries | ✅ Complete | React ErrorBoundary, graceful fallbacks |

---

## License

Proprietary — all rights reserved.
