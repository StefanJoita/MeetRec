# MeetRec — Sistem de Transcriere Automată a Ședințelor

Microservicii pentru înregistrarea, transcrierea și căutarea în procesele-verbale ale ședințelor de consiliu local. Audio intră în sistem, Whisper transcrie automat, textul devine căutabil în secunde.

---

## Arhitectură

```
                        ┌─────────────────────────────────┐
Fișier audio            │          BACKEND NETWORK         │
  ↓ (NFS/local)         │                                  │
┌──────────┐  LPUSH  ┌──────────┐  asyncpg  ┌───────────┐ │
│  Ingest  │────────▶│  Redis   │           │ PostgreSQL │ │
│  (M2)    │         │  Queue   │           │    (DB)    │ │
└──────────┘         └──────────┘           └───────────┘ │
                          │ BRPOP                 ↑        │
                     ┌────▼─────┐           asyncpg │      │
                     │  STT     │─────────────────  │      │
                     │  Worker  │  Whisper medium    │      │
                     │  (M4)    │                   │      │
                     └──────────┘                   │      │
                                                    │      │
                     ┌──────────┐  SQLAlchemy        │      │
                     │  API     │───────────────────┘      │
                     │  (M3)    │ :8080                    │
                     └──────────┘                         │
                          ↑                               │
                     ┌────┴────┐     ┌──────────────────┐ │
                     │  Nginx  │     │  Grafana + Loki   │ │
                     │  :443   │     │  (monitoring)     │ │
                     └─────────┘     └──────────────────┘ │
                          ↑                               └─
                     ┌────┴────┐
                     │Frontend │  (în lucru)
                     │  React  │
                     └─────────┘
```

---

## Status Implementare

| Modul | Serviciu | Status | Teste |
|-------|---------|--------|-------|
| M1 | Infrastructură (DB schema, docker-compose) | ✅ complet | — |
| M2 | Ingest (file watcher, validator, Redis publisher) | ✅ complet | ✅ 38 teste |
| M3 | REST API (FastAPI, SQLAlchemy, CRUD, FTS) | ✅ complet | ✅ 24 teste |
| M4 | STT Worker (Whisper, asyncpg, consumer loop) | ✅ complet | ✅ 78 teste |
| M5 | Search Indexer | 🔲 neimplementat | — |
| M6 | Audit & Retention | 🔲 neimplementat | — |
| M7 | Frontend React | 🔲 neimplementat | — |
| M8 | Nginx + HTTPS | 🔲 lipsă configurare | — |

**Pipeline funcțional end-to-end:** audio → ingest → Redis → STT Worker → PostgreSQL → API REST

---

## Cerințe preliminare

- **Docker Desktop** ≥ 24.0 (cu Compose v2)
- **RAM:** minim 6 GB liberi (4 GB pentru modelul Whisper medium + overhead)
- **Spațiu disc:** ~5 GB pentru imaginea stt-worker + ~1.5 GB pentru modelul Whisper
- **CPU:** orice x86-64 modern (transcriere ~2-4× timp real pe CPU)

---

## Setup la primul start

### 1. Clonare și configurare

```bash
git clone https://github.com/StefanJoita/MeetRec.git
cd MeetRec/meeting-transcriber

# Creează fișierul de configurare (nu se commitează în Git!)
cp .env.example .env
```

Editează `.env` și schimbă obligatoriu:
```bash
JWT_SECRET_KEY=<string-random-minim-32-caractere>
POSTGRES_PASSWORD=<parola-ta-sigura>
# Actualizează și în DATABASE_URL cu aceeași parolă:
DATABASE_URL=postgresql+asyncpg://mt_user:<parola-ta>@postgres:5432/meeting_transcriber
```

### 2. Pornire servicii (subset funcțional)

> **Notă:** La primul start, `stt-worker` descarcă ~1.5 GB modelul Whisper medium.
> Așteptați mesajul `model_loaded` în log-uri înainte să trimiteți audio.

```bash
# Pornire infrastructură + servicii implementate
docker compose up -d postgres redis api ingest stt-worker

# Urmărire log-uri (Ctrl+C pentru a ieși, serviciile rămân pornite)
docker compose logs -f
```

### 3. Verificare startup

```bash
docker compose ps
# Toate serviciile trebuie să fie "healthy" sau "running"

curl http://localhost:8080/health
# → {"status":"healthy","service":"meeting-transcriber-api","version":"1.0.0"}
```

---

## Testare manuală end-to-end

### Pas 1 — Verificare infrastructură

```bash
# PostgreSQL: verifică că schema e creată
docker compose exec postgres psql -U mt_user -d meeting_transcriber -c "\dt"
# → 5 tabele: recordings, transcripts, transcript_segments, audit_logs, users

# Redis: verifică conectivitatea
docker compose exec redis redis-cli PING
# → PONG

# API Swagger UI (doar în APP_ENV=development)
# Browser: http://localhost:8080/docs
```

### Pas 2 — Trimite un fișier audio

Copiază orice fișier `.mp3`, `.wav`, `.m4a`, `.ogg` sau `.flac` în inbox:

```bash
# Opțiunea A: docker compose cp
docker compose cp sedinta.mp3 mt-ingest:/data/inbox/sedinta.mp3

# Opțiunea B: copiez direct în directorul montat (dacă data/inbox/ e vizibil pe host)
cp sedinta.mp3 ./data/inbox/
```

Urmărești log-urile ingest:
```bash
docker compose logs -f ingest
# → file_detected  path=sedinta.mp3
# → audio_validated  duration=3612s  format=mp3
# → recording_created  recording_id=uuid...
# → job_published  queue=transcription_jobs
```

### Pas 3 — Verifică că recording-ul a apărut în API

```bash
curl http://localhost:8080/api/v1/recordings | python -m json.tool
# → {"items":[{"id":"<uuid>","filename":"sedinta.mp3","status":"queued",...}]}

# Salvează ID-ul pentru pașii următori
RECORDING_ID="<uuid-din-raspuns>"
```

### Pas 4 — Urmărești transcriere (STT Worker)

```bash
docker compose logs -f stt-worker
# → job_received  recording_id=...
# → mark_processing  model=whisper-medium
# → language_detected  lang=ro
# → transcribing  file=sedinta.mp3
# → save_results  segments=287  word_count=4312
# (durează 1-30 min în funcție de lungimea audio)

# Verifică statusul din API
curl http://localhost:8080/api/v1/recordings/$RECORDING_ID | python -m json.tool
# status progresează: queued → transcribing → completed
```

### Pas 5 — Citește transcrierea

```bash
curl http://localhost:8080/api/v1/transcripts/$RECORDING_ID | python -m json.tool
# → {
#     "id": "...",
#     "status": "completed",
#     "word_count": 4312,
#     "segments": [
#       {"segment_index": 0, "start_time": 0.0, "end_time": 4.8,
#        "text": "Ședința ordinară a consiliului local...", "confidence": 0.91},
#       ...
#     ]
#   }
```

### Pas 6 — Căutare full-text

```bash
curl "http://localhost:8080/api/v1/search?q=buget" | python -m json.tool
# → {"results":[{"recording_id":"...","headline":"...aprobarea <b>bugetului</b>...",
#                "rank":0.75,"matched_at":"2024-03-15T10:30:00"}]}

# Cu mai mulți termeni
curl "http://localhost:8080/api/v1/search?q=buget+infrastructura&limit=5"
```

### Pas 7 — Test caz de eroare (fișier invalid)

```bash
echo "acesta nu este audio" > fals.mp3
docker compose cp fals.mp3 mt-ingest:/data/inbox/fals.mp3

docker compose logs ingest --tail=10
# → validation_failed  reason=INVALID_AUDIO  file=fals.mp3
```

---

## API Reference

Documentație interactivă Swagger: **http://localhost:8080/docs**

| Endpoint | Metodă | Descriere |
|----------|--------|-----------|
| `/health` | GET | Status serviciu |
| `/api/v1/recordings` | GET | Listă înregistrări (paginat) |
| `/api/v1/recordings/{id}` | GET | Detalii înregistrare |
| `/api/v1/recordings/{id}` | DELETE | Șterge înregistrare |
| `/api/v1/recordings/{id}` | PATCH | Actualizează metadate |
| `/api/v1/transcripts/{recording_id}` | GET | Transcript cu segmente |
| `/api/v1/transcripts/{recording_id}/retry` | POST | Re-trimite la transcriere |
| `/api/v1/search` | GET | Căutare full-text (`?q=termen`) |

---

## Rulare teste unitare

```bash
# M2 — Ingest
cd services/ingest && pip install -r requirements.txt && pytest tests/ -v

# M3 — API
cd services/api && pip install -r requirements.txt && pytest tests/ -v

# M4 — STT Worker (nu necesită Whisper instalat — totul e mock-uit)
cd services/stt-worker && pip install pytest pytest-asyncio asyncpg redis pydantic-settings && pytest tests/ -v
```

Rezultate așteptate:
```
services/ingest:      38 passed
services/api:         24 passed
services/stt-worker:  78 passed (20 consumer + 20 postprocessor + 16 transcriber + 22 uploader)
```

---

## Probleme frecvente

| Problemă | Cauză | Soluție |
|----------|-------|---------|
| Build stt-worker durează 15-30 min | PyTorch CPU ~800 MB | Normal la primul build, cache-uit ulterior |
| `stt-worker` descarcă modelul la start | Whisper medium ~1.5 GB | Normal, o singură dată (volum persistent) |
| `password authentication failed` | Volum postgres vechi cu altă parolă | `docker volume rm meeting-transcriber_postgres_data` și restart |
| Port 8080 ocupat | Alt serviciu local | Schimbă `API_PORT` în `.env` |
| `audio_storage_path does not exist` | Volumul Docker nu e montat | `docker compose down && docker compose up -d` |
| Transcriere blocată la `transcribing` | Whisper încă încarcă modelul | Așteaptă `model_loaded` în `docker compose logs stt-worker` |

---

## Structura proiectului

```
meeting-transcriber/
├── database/
│   └── init.sql              — Schema PostgreSQL completă (tabele, trigger FTS, enum-uri)
├── services/
│   ├── ingest/               — M2: file watcher + validator + Redis publisher
│   │   ├── src/              — config, watcher, validator, processor, publisher, database
│   │   └── tests/            — 38 teste unitare
│   ├── api/                  — M3: FastAPI REST API
│   │   ├── src/              — routers, services, models, schemas, middleware
│   │   └── tests/            — 24 teste
│   ├── stt-worker/           — M4: Whisper STT consumer
│   │   ├── src/              — consumer, transcriber, uploader, language_detector, postprocessor
│   │   └── tests/            — 78 teste unitare
│   ├── search-indexer/       — M5: neimplementat
│   ├── audit-retention/      — M6: neimplementat
│   └── frontend/             — M7: neimplementat
├── docker-compose.yml        — Orchestrare completă (13 servicii)
├── .env.example              — Template configurare
└── README.md                 — Acest fișier
```
