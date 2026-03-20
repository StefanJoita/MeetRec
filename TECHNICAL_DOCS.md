# MeetRec — Technical Documentation

> Documentație tehnică detaliată. Pentru o prezentare generală a proiectului, vezi [README.md](README.md).

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Project Structure](#2-project-structure)
3. [Key Modules Explanation](#3-key-modules-explanation)
4. [Important Classes and Functions](#4-important-classes-and-functions)
5. [Data Structures](#5-data-structures)
6. [Dependencies](#6-dependencies)
7. [Configuration](#7-configuration)
8. [Error Handling and Logging](#8-error-handling-and-logging)
9. [Possible Improvements](#9-possible-improvements)

---

## 1. Architecture Overview

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
| **API Service** | FastAPI + SQLAlchemy | REST API, business logic, JWT auth, audit, export |
| **Ingest Service** | watchdog + asyncpg | File system watcher, validator, queue publisher |
| **STT Worker** | OpenAI Whisper + asyncpg | Speech-to-text transcription engine |
| **PostgreSQL** | postgres:15-alpine | Primary data store (recordings, transcripts, audit) |
| **Redis** | redis:7-alpine | FIFO job queue between Ingest and STT Worker |
| **Nginx** | nginx:1.25-alpine | Reverse proxy, HTTPS termination, rate limiting |
| **Frontend** | React + Vite + TailwindCSS | Web UI cu login, listă înregistrări, detaliu, căutare, admin |
| **Audit-Retention** | Python service | Ștergere programată a înregistrărilor expirate (Dockerfile gata) |
| **Grafana / Loki / Promtail** | Grafana stack | Agregare loguri și dashboards |

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
   ├── GET /api/v1/search?q=buget+2024
   └── GET /api/v1/export/{id}?format=pdf
```

---

## 2. Project Structure

```
meeting-transcriber/
│
├── docker-compose.yml          # Orchestrează toate containerele
├── .env.example                # Template variabile de mediu
├── Makefile                    # Comenzi rapide (make start, make logs)
│
├── database/
│   ├── init.sql                # Schema PostgreSQL completă (ENUM-uri, indexuri, triggere)
│   └── migrations/             # Placeholder pentru viitoarele migrări Alembic
│
├── services/
│   │
│   ├── api/                    # Backend REST FastAPI
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── src/
│   │   │   ├── main.py         # Inițializare app, middleware, lifecycle
│   │   │   ├── config.py       # Pydantic Settings (citit din .env)
│   │   │   ├── database.py     # Motor SQLAlchemy async + dependency get_db()
│   │   │   ├── models/
│   │   │   │   ├── base.py         # SQLAlchemy declarative Base
│   │   │   │   ├── recording.py    # Model ORM Recording + enum-uri
│   │   │   │   ├── transcript.py   # Transcript + TranscriptSegment ORM
│   │   │   │   └── audit_log.py    # AuditLog + User ORM
│   │   │   ├── routers/
│   │   │   │   ├── recordings.py   # CRUD: /api/v1/recordings
│   │   │   │   ├── transcript.py   # /api/v1/transcripts/recording/{id}
│   │   │   │   ├── search.py       # /api/v1/search?q=...
│   │   │   │   ├── export.py       # /api/v1/export/{id}?format=pdf|docx|txt
│   │   │   │   ├── auth.py         # /api/v1/auth/login, /logout, /me
│   │   │   │   └── audit.py        # /api/v1/audit-logs (doar admin)
│   │   │   ├── schemas/
│   │   │   │   └── recording.py    # Toate schemele Pydantic request/response
│   │   │   ├── services/
│   │   │   │   ├── recording_service.py  # Logică business CRUD înregistrări
│   │   │   │   ├── transcript_service.py # Preluare transcriere + retry
│   │   │   │   └── search_service.py     # Logică query FTS PostgreSQL
│   │   │   └── middleware/
│   │   │       ├── audit.py        # Funcție helper log_audit()
│   │   │       └── auth.py         # JWT encode/decode, dependency get_current_user
│   │   └── tests/
│   │       ├── conftest.py
│   │       ├── test_health.py
│   │       └── test_recordings.py
│   │
│   ├── ingest/                 # Watcher fișiere + pipeline ingest
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── src/
│   │   │   ├── main.py         # Entry point: startup, signal handlers, shutdown
│   │   │   ├── config.py       # Pydantic Settings pentru ingest
│   │   │   ├── logger.py       # Configurare structlog
│   │   │   ├── watcher.py      # InboxWatcher + AudioFileHandler (watchdog)
│   │   │   ├── processor.py    # FileProcessor: validate→store→db→publish
│   │   │   ├── validator.py    # AudioValidator: format, dimensiune, hash, metadate mutagen
│   │   │   ├── storage.py      # StorageManager: plasare fișiere cu organizare pe dată
│   │   │   ├── publisher.py    # JobPublisher: LPUSH Redis cu retry
│   │   │   └── database.py     # DatabaseClient: asyncpg + INSERT înregistrare
│   │   └── tests/
│   │       └── test_validator.py
│   │
│   ├── stt-worker/             # Worker Whisper speech-to-text
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── src/
│   │   │   ├── main.py             # Entry point: încărcare model, pornire consumer, SIGTERM
│   │   │   ├── config.py           # Pydantic Settings pentru stt-worker
│   │   │   ├── consumer.py         # JobConsumer: buclă BRPOP, orchestrare pipeline
│   │   │   ├── transcriber.py      # WhisperTranscriber: model, transcriere (thread pool)
│   │   │   ├── language_detector.py# LanguageDetector: detectare limbă din primele 30s
│   │   │   ├── postprocessor.py    # PostProcessor: diacritice, normalizare spații
│   │   │   └── uploader.py         # DatabaseUploader: bulk INSERT asyncpg
│   │   └── tests/
│   │       ├── conftest.py
│   │       ├── test_consumer.py
│   │       ├── test_postprocessor.py
│   │       ├── test_transcriber.py
│   │       └── test_uploader.py
│   │
│   ├── search-indexer/         # (placeholder — neimplementat)
│   │   └── src/
│   │
│   └── audit-retention/        # Ștergere programată înregistrări expirate
│       ├── Dockerfile
│       └── src/                # (sursa neimplementată încă)
│
├── frontend/                   # Aplicație React + Vite
│   ├── Dockerfile
│   ├── package.json
│   └── src/
│       ├── main.tsx            # Entry point React
│       ├── App.tsx             # Router, rute protejate, AuthProvider
│       ├── index.css           # Stiluri Tailwind
│       ├── api/                # Clienți API cu tipuri TypeScript
│       │   ├── client.ts       # Instanță Axios cu interceptor JWT
│       │   ├── auth.ts         # login(), logout(), getMe()
│       │   ├── recordings.ts   # CRUD înregistrări
│       │   ├── transcripts.ts  # getTranscript(), retryTranscription()
│       │   ├── search.ts       # searchTranscripts()
│       │   └── types.ts        # Tipuri TypeScript partajate
│       ├── contexts/
│       │   └── AuthContext.tsx # Hook useAuth(), stare JWT, login/logout
│       ├── components/
│       │   ├── layout/
│       │   │   └── AppShell.tsx      # Sidebar, topbar, navigație
│       │   ├── AudioPlayer.tsx       # Player HTML5 cu sincronizare segmente
│       │   ├── TranscriptViewer.tsx  # Transcriere scrollabilă cu segment activ evidențiat
│       │   └── ui/
│       │       ├── Spinner.tsx
│       │       └── StatusBadge.tsx   # Chip colorat per status înregistrare
│       └── pages/
│           ├── LoginPage.tsx         # Formular autentificare JWT
│           ├── RecordingsListPage.tsx# Listă paginată cu filtru status
│           ├── RecordingDetailPage.tsx # Detaliu + audio player + transcriere
│           ├── NewRecordingPage.tsx  # Formular upload (metadate + fișier)
│           ├── SearchPage.tsx        # UI căutare full-text cu snippets evidențiate
│           ├── AdminPage.tsx         # Vizualizare audit log (doar rol admin)
│           └── NotFoundPage.tsx
│
├── monitoring/
│   ├── loki/loki-config.yaml
│   ├── grafana/datasources/
│   └── promtail/promtail-config.yaml
│
├── nginx/
└── data/
    └── inbox/                  # Drop-folder pentru fișiere audio (montat ca volum)
```

---

## 3. Key Modules Explanation

### 3.1 API Service — `services/api/src/`

| Modul | Scop | Interacționează cu |
|---|---|---|
| `main.py` | Factory FastAPI, middleware, lifecycle | Toate routerele |
| `config.py` | Settings tipizate din environment | Toate modulele |
| `database.py` | Motor SQLAlchemy async, dependency `get_db()` | Servicii, routere |
| `models/` | ORM (Recording, Transcript, AuditLog, User) | Servicii, DB |
| `schemas/` | Scheme Pydantic validare request/response | Routere |
| `routers/recordings.py` | CRUD înregistrări, upload fișier | RecordingService |
| `routers/transcript.py` | Get transcriere + segmente, retry | TranscriptService |
| `routers/search.py` | Căutare full-text | SearchService |
| `routers/export.py` | Descărcare transcriere ca PDF / DOCX / TXT | TranscriptService |
| `routers/auth.py` | `POST /auth/login`, `/logout`, `/me` | User model, middleware auth |
| `routers/audit.py` | Vizualizare paginată audit log (doar admin) | Model AuditLog |
| `middleware/audit.py` | Scrie intrări audit log prin sesiunea curentă DB | Model AuditLog |
| `middleware/auth.py` | Generare/validare JWT, `get_current_user`, `get_current_admin` | Model User |

### 3.2 Ingest Service — `services/ingest/src/`

Daemon de background care urmărește `/data/inbox/` și declanșează pipeline-ul de ingestie pentru orice fișier audio nou.

| Modul | Scop |
|---|---|
| `main.py` | Entry point async; conectează componentele, înregistrează handlere SIGTERM/SIGINT |
| `watcher.py` | `InboxWatcher` învelește watchdog `Observer`; `AudioFileHandler` gestionează evenimentele `on_created` / `on_moved`. Așteaptă stabilizarea fișierului înainte de procesare. |
| `processor.py` | `FileProcessor` — pattern Facade. Apelează validator → storage → database → publisher în secvență cu rollback la eșec |
| `validator.py` | `AudioValidator` — validează extensia, dimensiunea, hash-ul, durata cu `mutagen` |
| `storage.py` | `StorageManager` — mută fișierele în `/data/processed/YYYY/MM/DD/{uuid}.ext` |
| `publisher.py` | `JobPublisher` — serializează `TranscriptionJob` în JSON și `LPUSH` în Redis cu retry exponențial |
| `database.py` | `DatabaseClient` — bazat pe asyncpg; creează rânduri recording + transcript; verifică duplicat prin hash SHA256 |

### 3.3 STT Worker — `services/stt-worker/src/`

Worker de background care consumă joburi din Redis, rulează inferența Whisper într-un thread pool și scrie rezultatele în PostgreSQL.

| Modul | Scop |
|---|---|
| `main.py` | Startup: conectare DB → încărcare model → pornire consumer. Gestionează SIGTERM grațios |
| `consumer.py` | `JobConsumer` — buclă BRPOP; orchestrează pipeline-ul de 7 pași per job |
| `transcriber.py` | `WhisperTranscriber` — învelește Whisper în `run_in_executor` pentru a nu bloca event loop-ul async |
| `language_detector.py` | `LanguageDetector` — folosește modelul Whisper deja încărcat pentru a detecta limba din primele 30 de secunde |
| `postprocessor.py` | `PostProcessor` — corectează diacriticele românești (cedilă→virgulă), normalizează spațiile |
| `uploader.py` | `DatabaseUploader` — bulk INSERT asyncpg pentru segmente + UPDATE status transcriere/înregistrare |
| `config.py` | Pydantic Settings; validează că `audio_storage_path` există (montură read-only) |

### 3.4 Frontend — `frontend/src/`

Single-page application React cu rute protejate JWT. Toate rutele în afară de `/login` necesită autentificare.

| Modul | Scop |
|---|---|
| `App.tsx` | Configurare router cu wrapper `ProtectedRoute`; învelește app-ul în `AuthProvider` |
| `contexts/AuthContext.tsx` | Stare globală auth: `user`, `login()`, `logout()`, token în `localStorage` |
| `api/client.ts` | Instanță Axios cu interceptor de request care injectează header-ul `Authorization: Bearer` |
| `pages/RecordingDetailPage.tsx` | Metadate înregistrare + `AudioPlayer` + `TranscriptViewer` sincronizate |
| `pages/SearchPage.tsx` | Formular căutare cu rezultate live; randează HTML snippets `ts_headline` în siguranță |
| `pages/AdminPage.tsx` | Tabel paginat audit log; accesibil doar utilizatorilor cu rol admin |
| `components/AudioPlayer.tsx` | Player HTML5 care evidențiază segmentul activ din transcriere pe măsură ce audio se redă |
| `components/TranscriptViewer.tsx` | Listă segmente scrollabilă; click pe segment poziționează player-ul audio |

---

## 4. Important Classes and Functions

### `RecordingService` (`services/api/src/services/recording_service.py`)

Logică business centrală pentru înregistrări. Routerul o apelează; nu atinge HTTP direct.

| Metodă | Descriere |
|---|---|
| `list_recordings()` | Query paginat, filtrabil, sortabil cu SQLAlchemy ORM. Numără înainte de slice. |
| `get_by_id()` | Preia o înregistrare; SQLAlchemy încarcă automat transcrierea asociată via `lazy="selectin"` |
| `create()` | Creează un rând `Recording` și un rând `Transcript` asociat (status=pending) într-un singur flush |
| `process_upload()` | Citește bytes fișier uploadat, calculează SHA256, salvează pe disc, actualizează înregistrarea, publică job Redis |
| `update()` | Semantici PATCH: `model_dump(exclude_unset=True)` aplică doar câmpurile furnizate |
| `delete()` | Șterge fișierul fizic de pe disc + rândul din DB (CASCADE șterge transcriere + segmente) |
| `_publish_job()` | Deschide conexiune async Redis, `LPUSH` JSON job, închide conexiunea |

### `FileProcessor` (`services/ingest/src/processor.py`)

**Facade** care conectează patru dependențe injectate.

```
process(file_path)
  ├── Step 1: validator.validate(file_path)         → ValidationResult
  ├── Step 2: database.check_duplicate(hash)        → existing_id or None
  ├── Step 3: storage.store_file(metadata)          → stored_path
  ├── Step 4: database.create_recording(metadata)   → recording_id
  └── Step 5: publisher.publish_transcription_job() → bool
```

Erorile la pasul 3 returnează `False` și lasă fișierul din inbox neatins. Erorile la pasul 5 lasă înregistrarea în DB cu status `queued` pentru un retry viitor — fișierul nu este dat rollback.

### `JobConsumer` (`services/stt-worker/src/consumer.py`)

Implementează bucla principală a worker-ului. Folosește `redis.asyncio` (BRPOP non-blocant) astfel încât event loop-ul asyncio rămâne liber în timp ce așteaptă joburi.

**Pipeline per job:**
```
_process_job(job)
  ├── Step 1: get_transcript_id(recording_id)
  ├── Step 2: mark_processing(transcript_id)           → DB status = 'processing'
  ├── Step 3: detector.detect(file_path)               → cod limbă ("ro")
  ├── Step 4: transcriber.transcribe(file_path, lang)  → List[TranscriptSegment]
  ├── Step 5: postprocessor.process(segments)          → List[TranscriptSegment]
  ├── Step 6: _compute_metadata(segments)              → TranscriptMetadata
  └── Step 7: uploader.save_results(...)               → DB status = 'completed'
```

La orice excepție: `mark_failed()` este apelat cu mesajul de eroare. Worker-ul **nu se oprește** — continuă cu următorul job.

### `WhisperTranscriber` (`services/stt-worker/src/transcriber.py`)

Învelește biblioteca Whisper sincronă pentru a fi sigură într-un context async.

- **`load_model()`** — apelează `whisper.load_model()` via `run_in_executor()` (blocant, 5–30 s)
- **`transcribe()`** — apelează `_run_whisper_sync()` via `run_in_executor()` (blocant, minute)
- **`_convert_segment()`** — convertește dict-ul raw Whisper în `TranscriptSegment`; convertește `avg_logprob` (log-probabilitate) în scor de confidență liniar `[0.0, 1.0]` limitat pentru coloana DB `DECIMAL(4,3)`

### `AudioValidator` (`services/ingest/src/validator.py`)

Aplică strategia "verificarea cea mai ieftină primul":

1. Fișierul există și este un fișier regular
2. Extensia este în setul permis
3. Dimensiunea fișierului este între 1 byte și 500 MB
4. Hash SHA256 calculat (streaming, chunk-uri de 8 MB — eficient pentru fișiere mari)
5. `mutagen.File()` citește header-ele audio — extrage durată, sample rate, canale, bitrate
6. Durata trebuie să fie între 5 secunde și 12 ore

### `SearchService` (`services/api/src/services/search_service.py`)

Execută un query SQL raw împotriva indexului full-text search PostgreSQL:

- Folosește `plainto_tsquery('romanian', :query)` — acceptă limbaj natural (nu necesită sintaxă de operator)
- Ordonează rezultatele după `ts_rank` (scor relevanță)
- Returnează `ts_headline` — un snippet text cu termenul potrivit înfășurat în `<b>...</b>`
- Filtrează pe `transcripts.status = 'completed'` și `search_vector @@ tsquery`

### `log_audit()` (`services/api/src/middleware/audit.py`)

Funcție async simplă apelată explicit în fiecare router după operații importante. Extrage IP-ul real al clientului din header-ele `X-Real-IP` / `X-Forwarded-For` (setate de Nginx). Intrarea de audit log este adăugată la **aceeași sesiune DB** — commitată atomic cu operația business.

### `DatabaseUploader.save_results()` (`services/stt-worker/src/uploader.py`)

Folosește `asyncpg.executemany()` pentru bulk INSERT al segmentelor de transcriere — tipic de 60× mai rapid decât apeluri individuale `execute()`. Toate cele trei operații (INSERT segmente, UPDATE transcript, UPDATE recording) se întâmplă într-o singură tranzacție. Folosește `ON CONFLICT DO NOTHING` pentru idempotență (sigur de reîncercat dacă worker-ul se oprește pe parcurs).

### Auth Router (`services/api/src/routers/auth.py`)

| Endpoint | Descriere |
|---|---|
| `POST /api/v1/auth/login` | Verifică username + parolă (bcrypt), returnează JWT semnat |
| `POST /api/v1/auth/logout` | Înregistrează logout în audit log (invalidarea token-ului este pe client) |
| `GET /api/v1/auth/me` | Returnează profilul utilizatorului autentificat curent |

---

## 5. Data Structures

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
    file_hash_sha256: str       # string hex de 64 caractere
    audio_format: str           # "mp3", "wav", etc.
    duration_seconds: int
    sample_rate_hz: Optional[int]
    channels: Optional[int]
    bitrate_kbps: Optional[int]
```

Produs de `AudioValidator.validate()` și transmis prin întreg pipeline-ul de ingestie (către `StorageManager`, `DatabaseClient`, `JobPublisher`).

### `TranscriptSegment` (Python dataclass — STT Worker)

```python
@dataclass
class TranscriptSegment:
    segment_index: int       # ordine 0-based
    start_time: float        # secunde de la începutul audio, ex. 12.500
    end_time: float          # ex. 17.320
    text: str                # "Bună ziua, doamnă primar."
    confidence: float        # 0.0–1.0 (din Whisper avg_logprob)
    language: str            # "ro", "en", etc.
```

### `TranscriptionJob` (publicat în Redis)

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

**Recording Status** (progresie liniară):
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

| Schemă | Utilizată pentru |
|---|---|
| `RecordingCreate` | `POST /recordings` — validează titlu, meeting_date (nu în viitor), participanți |
| `RecordingUpdate` | `PATCH /recordings/{id}` — toate câmpurile opționale (semantici PATCH) |
| `RecordingResponse` | Detaliu complet înregistrare. Exclude `file_path` (securitate) |
| `RecordingListItem` | Item compact pentru listă cu status transcriere |
| `PaginatedRecordings` | Învelește lista + total + pagină + pagini |
| `TranscriptResponse` | Transcriere completă cu `List[SegmentResponse]` și `full_text` |
| `SearchResult` | Un rezultat: timestamps, snippet text, `headline` cu tag-uri `<b>`, `rank` |
| `SearchResponse` | Învelește rezultate + `total_results` + `search_time_ms` |
| `UploadResponse` | Returnat la `POST /{id}/upload` — include timp estimat de procesare |
| `LoginRequest` | `POST /auth/login` — `username` + `password` |
| `TokenResponse` | JWT `access_token` + `token_type` + expirare |

---

## 6. Dependencies

### API Service

| Bibliotecă | Versiune | Scop |
|---|---|---|
| `fastapi` | 0.111.0 | Framework REST async cu documentație OpenAPI automată |
| `uvicorn[standard]` | 0.29.0 | Server ASGI |
| `pydantic` | 2.7.1 | Validare și serializare date |
| `pydantic-settings` | 2.2.1 | Încarcă `Settings` din `.env` și variabile de mediu |
| `sqlalchemy` | 2.0.30 | ORM async (declarativ, tipizat cu `Mapped[]`) |
| `asyncpg` | 0.29.0 | Driver PostgreSQL async rapid |
| `alembic` | 1.13.1 | Migrări bază de date (nefolosit în producție încă) |
| `python-jose[cryptography]` | 3.3.0 | Generare și verificare token JWT (HS256) |
| `passlib[bcrypt]` | 1.7.4 | Hash parole cu bcrypt |
| `redis` | 5.0.4 | Client Redis async (publicare joburi transcriere) |
| `python-multipart` | 0.0.9 | Parsare upload fișiere în FastAPI |
| `aiofiles` | 23.2.1 | I/O fișiere async |
| `reportlab` | 4.1.0 | Generare PDF pentru export transcriere |
| `python-docx` | 1.1.0 | Generare DOCX pentru export transcriere |
| `structlog` | 24.2.0 | Logare JSON structurată |
| `tenacity` | 8.3.0 | Decorator retry cu backoff exponențial |
| `httpx` | 0.27.0 | Client HTTP async |

### Ingest Service

| Bibliotecă | Versiune | Scop |
|---|---|---|
| `watchdog` | 3.0.0 | Monitorizare nativă OS a sistemului de fișiere (inotify pe Linux) |
| `mutagen` | 1.47.0 | Extragere metadate audio (format, durată, sample rate) fără decodare completă |
| `pydub` | 0.25.1 | Validare suplimentară fișiere audio (învelește ffmpeg) |
| `asyncpg` | 0.29.0 | Driver PostgreSQL async |
| `redis` | 5.0.1 | Client Redis pentru LPUSH |
| `tenacity` | 8.2.3 | Retry pentru publicare Redis |
| `structlog` | 24.1.0 | Logare JSON |

### STT Worker

| Bibliotecă | Versiune | Scop |
|---|---|---|
| `openai-whisper` | latest | Motor STT principal — model transformer multilingv |
| `numpy` | <2.0 | Necesar de PyTorch/Whisper (numpy 2.x incompatibil cu torch 2.1.0) |
| `torch` | 2.1.0+cpu | Runtime deep learning (build CPU-only pentru servere fără GPU) |
| `asyncpg` | 0.29.0 | PostgreSQL async pentru bulk INSERT segmente |
| `redis` | 5.0.1 | Client Redis async (`redis.asyncio`) pentru BRPOP |
| `structlog` | 24.1.0 | Logare JSON |
| `tenacity` | 8.2.3 | Retry pentru reziliență la conexiune |

### Frontend

| Bibliotecă | Scop |
|---|---|
| `react` + `react-dom` | Bibliotecă UI |
| `react-router-dom` | Routing client-side cu suport rute protejate |
| `@tanstack/react-query` | Gestionare stare server, caching, refetch background |
| `axios` | Client HTTP cu interceptor JWT |
| `tailwindcss` | CSS utility-first |
| `lucide-react` | Set icoane |
| `vite` | Build tool și server dev |

---

## 7. Configuration

Toată configurația este gestionată prin variabile de mediu încărcate dintr-un fișier `.env`. Clasele Pydantic `Settings` din fiecare serviciu validează tipurile la startup — dacă o variabilă obligatorie lipsește, serviciul **refuză să pornească** cu un mesaj de eroare clar.

### Core Variables

| Variabilă | Default | Obligatorie | Descriere |
|---|---|---|---|
| `DATABASE_URL` | — | ✅ | String conexiune PostgreSQL. Format: `postgresql+asyncpg://user:pass@host:port/db` |
| `POSTGRES_USER` | — | ✅ | Username PostgreSQL |
| `POSTGRES_PASSWORD` | — | ✅ | Parolă PostgreSQL |
| `POSTGRES_DB` | — | ✅ | Nume bază de date PostgreSQL |
| `JWT_SECRET_KEY` | — | ✅ | Cheie semnare HS256 (min. 32 caractere recomandat) |
| `REDIS_URL` | `redis://redis:6379` | | URL conexiune Redis |
| `REDIS_TRANSCRIPTION_QUEUE` | `transcription_jobs` | | Numele listei Redis pentru coada de joburi |
| `APP_ENV` | `development` | | `development` activează `/docs`, CORS permisiv |
| `LOG_LEVEL` | `INFO` | | Verbozitate logare: `DEBUG`, `INFO`, `WARNING`, `ERROR` |

### Storage Variables

| Variabilă | Default | Descriere |
|---|---|---|
| `INBOX_PATH` | `/data/inbox` | Director urmărit de Ingest Service |
| `AUDIO_STORAGE_PATH` | `/data/processed` | Stocare organizată pentru fișierele audio validate |
| `EXPORT_PATH` | `/data/exports` | Director output pentru exporturi PDF/DOCX |
| `MAX_FILE_SIZE_BYTES` | `524288000` | Limită upload 500 MB |

### Auth Variables

| Variabilă | Default | Descriere |
|---|---|---|
| `JWT_ALGORITHM` | `HS256` | Algoritm semnare JWT |
| `JWT_EXPIRE_MINUTES` | `480` | Durată de viață token (8 ore) |

### Whisper Variables

| Variabilă | Default | Descriere |
|---|---|---|
| `WHISPER_MODEL` | `medium` | Dimensiune model: `tiny`, `base`, `small`, `medium`, `large` |
| `WHISPER_PRIMARY_LANGUAGE` | `ro` | Hint limbă implicit transmis la Whisper |
| `WHISPER_MODEL_PATH` | `/app/models` | Director persistent pentru fișierele model cache |

### Retention Variables

| Variabilă | Default | Descriere |
|---|---|---|
| `RETENTION_DAYS` | `1095` | 3 ani — cât timp se păstrează înregistrările |
| `AUDIT_LOG_RETENTION_DAYS` | (default serviciu) | Cât timp se păstrează intrările de audit log |

### Grafana

| Variabilă | Default | Descriere |
|---|---|---|
| `GRAFANA_ADMIN_PASSWORD` | — | Parolă admin pentru UI Grafana |
| `GRAFANA_PORT` | `3000` | Port host pentru Grafana |
| `NGINX_HTTPS_PORT` | `443` | Port host pentru Nginx HTTPS |

---

## 8. Error Handling and Logging

### Strategia de gestionare a erorilor

**Ingest Service:**
- Fișierele care eșuează validarea sunt mutate în `/data/inbox/errors/` pentru inspecție manuală (nu șterse)
- Fișierele duplicate (același hash SHA256) sunt șterse silențios din inbox
- Dacă storage eșuează (pasul 3), funcția returnează `False` și lasă fișierul din inbox pe loc
- Dacă DB eșuează (pasul 4), fișierul stocat este șters (rollback manual) pentru a menține consistența
- Dacă publicarea Redis eșuează (pasul 5), înregistrarea rămâne în DB cu status `queued` — un job de recuperare poate republica mai târziu
- Publicarea Redis reîncearcă cu backoff exponențial (1s → 2s → 4s, max 3 încercări) folosind `tenacity`

**STT Worker:**
- Orice excepție în procesarea unui job declanșează `mark_failed()` — înregistrează mesajul de eroare în `transcripts.error_message`
- Worker-ul **nu se oprește niciodată** din cauza unui singur eșec de job — loghează eroarea și continuă cu următorul job
- Dacă Redis este temporar indisponibil, `_poll_once()` doarme 5 secunde și reîncearcă (evită spam log)
- Shutdown grațios: `consumer.stop()` setează `_running = False`; transcrierea curentă are voie să se termine înainte ca procesul să iasă

**API Service:**
- Un handler global `@app.exception_handler(Exception)` prinde orice excepție netrată și returnează `500` cu un mesaj generic (fără stack trace expus clientului)
- `HTTPException` este folosit pentru erori așteptate (404, 400, 401, 403)
- Sesiunea DB în `get_db()` face auto-commit la succes și auto-rollback la excepție
- Intrările de audit log sunt scrise în aceeași tranzacție cu operația business — fie ambele reușesc, fie ambele eșuează

### Logare

Toate serviciile folosesc **`structlog`** cu format de output JSON:

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

Logurile structurate (câmpuri key=value, nu string-uri libere) permit **Loki / Grafana** să filtreze și să agrege după orice câmp:
- `event = "job_failed"` → alertă la eșecuri de transcriere
- `event = "file_rejected"` → monitorizare upload-uri de fișiere greșite
- `event = "redis_brpop_error"` → alertă la probleme de conectivitate coadă

Niveluri de log folosite:
- `DEBUG` — informații detaliate query (SQL echo în development)
- `INFO` — evenimente flux normal (fișier detectat, job pornit, job finalizat)
- `WARNING` — probleme recuperabile (fișier duplicat, override limbă, timeout stabilitate fișier)
- `ERROR` — eșecuri care necesită atenție (eroare DB, eșec storage, excepție netrată)

---

## 9. Possible Improvements

### Arhitectură

1. **Durabilitate message broker** — Redis `BRPOP` nu este cu adevărat fiabil: dacă worker-ul se oprește între `BRPOP` și `mark_processing`, jobul se pierde. Considerați Redis Streams (cu consumer groups și `XACK`) sau RabbitMQ pentru garanții de livrare cel-puțin-o-dată.

2. **Concurență worker** — STT Worker procesează un singur job simultan (`stt_worker_concurrency = 1`). `config.py` include deja această setare. Scalați orizontal rulând mai multe containere `stt-worker` (Redis BRPOP distribuie joburile automat).

3. **Diarizare vorbitori** — Coloana `speaker_id` există în `transcript_segments` dar nu este niciodată populată. Integrați `pyannote-audio` pentru a identifica cine vorbește fiecare segment.

4. **Suport GPU** — Fișierul Docker Compose include configurație GPU comentată. Cu un GPU NVIDIA și build-ul Whisper activat pentru CUDA, transcrierea ar fi de 10–20× mai rapidă.

5. **Serviciu search-indexer** — Directorul `services/search-indexer/` este un placeholder. Un indexer dedicat ar putea menține actualizări ale indexului FTS în timp real, independent de STT Worker.

### Calitatea codului

6. **Migrări Alembic** — Directorul `database/migrations/` este gol. Toată schema este definită în `init.sql` (rulează o singură dată). Pentru producție, introduceți Alembic pentru a gestiona evoluția schemei în siguranță.

7. **Reutilizare conexiune Redis** — `RecordingService._publish_job()` deschide și închide o conexiune Redis la fiecare upload. Ar trebui să folosească un connection pool partajat (injectabil ca dependency FastAPI).

8. **Serviciu Audit-Retention** — Dockerfile-ul există dar sursa nu a fost implementată. Logica schedulerului de retenție (query înregistrări expirate, ștergere fișiere din NFS, eliminare rânduri DB) trebuie scrisă în `services/audit-retention/src/`.

### Operațional

9. **Health endpoints** — API-ul are `/health`. Ingest Service și STT Worker nu au health endpoints — Docker poate releva doar dacă procesul trăiește. Adăugați probe TCP sau HTTP simple.

10. **Metrici** — Nu sunt exportate metrici Prometheus. Expuneți metrici (adâncime coadă, durată transcriere, rată eșec) pentru observabilitate mai bună dincolo de scanarea logurilor.

11. **Race condition deduplicare fișiere** — Între `check_duplicate()` și `create_recording()`, un al doilea fișier identic ar putea trece verificarea de duplicat. Constraintul `UNIQUE` la nivel de bază de date pe `file_hash_sha256` este protecția corectă — asigurați-vă că excepția `UniqueViolation` este prinsă și tratată grațios.

---
