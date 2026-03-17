# Deploy Parțial + Ghid de Testare Manuală

## Context

Avem 3 servicii complet implementate (ingest, stt-worker, api) + infrastructura (postgres, redis).
Serviciile neimplementate (frontend, audit-retention, search-indexer) nu au Dockerfile → nu pot fi pornite.
Nginx nu are fișier de configurare → nu poate fi pornit.

Scopul: pornire subset funcțional, testare manuală end-to-end a pipeline-ului audio → transcriere → API.

---

## Servicii deployabile acum

| Serviciu | Status | Dockerfile |
|----------|--------|------------|
| postgres | ✓ imagine oficială | nu e necesar |
| redis | ✓ imagine oficială | nu e necesar |
| ingest | ✓ implementat | ✓ există |
| stt-worker | ✓ implementat (M4) | ✓ există |
| api | ✓ implementat | ✓ există |
| nginx | ✗ lipsă nginx.conf | — |
| frontend | ✗ lipsă src + Dockerfile | — |
| audit-retention | ✗ lipsă src + Dockerfile | — |

---

## Pași de implementare

### 1. Creare `.env`
- Copiat `.env.example` → `.env`
- Ajustări pentru dev local:
  - `DATABASE_URL` — deja corect (postgresql+asyncpg://)
  - `JWT_SECRET_KEY` — schimbat cu un string random de 32+ caractere
  - `AUDIO_STORAGE_PATH=/data/processed` — rămâne ca-n compose
  - `INBOX_PATH=/data/inbox` — rămâne ca-n compose
  - `WHISPER_MODEL_PATH=/app/models` — montat ca volum în compose
  - `APP_ENV=development`

### 2. Pornire servicii (subset)
```bash
cd meeting-transcriber
docker compose up -d postgres redis api ingest stt-worker
```

### 3. Verificare startup
```bash
docker compose ps
docker compose logs api --tail=20
docker compose logs stt-worker --tail=30   # "Loading Whisper model..." → durează
docker compose logs ingest --tail=20
```

---

## Ghid testare manuală

### Test 1: Infrastructura
```bash
docker compose exec postgres psql -U mt_user -d meeting_transcriber -c "\dt"
docker compose exec redis redis-cli PING
curl http://localhost:8080/health
# Browser: http://localhost:8080/docs
```

### Test 2: Upload audio → ingest
```bash
docker compose cp test.mp3 mt-ingest:/data/inbox/test.mp3
docker compose logs -f ingest
# → file_detected → audio_validated → job_published → recording_created
```

### Test 3: Recording creat în DB
```bash
curl http://localhost:8080/api/v1/recordings
# → {"items":[{"id":"uuid...","filename":"test.mp3","status":"queued",...}]}
RECORDING_ID="uuid-din-raspuns"
```

### Test 4: Transcriere (STT Worker)
```bash
docker compose logs -f stt-worker
# → job_received → mark_processing → transcribing → save_results
# (1-10 minute în funcție de lungimea audio)
curl http://localhost:8080/api/v1/recordings/$RECORDING_ID
# → status: queued → transcribing → completed
```

### Test 5: Citire transcriere
```bash
curl http://localhost:8080/api/v1/transcripts/$RECORDING_ID
# → {"status":"completed","segments":[{"text":"...","start_time":0.0,...}]}
```

### Test 6: Căutare full-text
```bash
curl "http://localhost:8080/api/v1/search?q=buget"
# → {"results":[{"recording_id":"...","headline":"...buget..."}]}
```

### Test 7: Fișier invalid (test eroare)
```bash
echo "not audio" > fake.mp3
docker compose cp fake.mp3 mt-ingest:/data/inbox/fake.mp3
docker compose logs -f ingest
# → validation_failed
```

---

## Fișiere de creat/modificat

| Fișier | Acțiune |
|--------|---------|
| `.env` | creat din `.env.example` + JWT_SECRET_KEY random |
| `docker-compose.yml` | NU modificăm — pornim selectiv cu servicii specifice |

---

## Potențiale probleme la primul build

| Problemă | Cauză | Fix |
|----------|-------|-----|
| Build stt-worker 15-30 min | PyTorch CPU ~800MB | Normal la primul build |
| "Downloading Whisper model..." | Modelul medium ~1.5GB | Normal, o singură dată |
| Port 8080 ocupat | Alt proces local | Schimbă `API_PORT` în `.env` |
| DB connection refused la start | Postgres nu e ready | Adaugă `sleep 5` sau re-run `docker compose up -d api` |

---

## Pipeline end-to-end

```
/data/inbox/test.mp3
    ↓ ingest: validare + DB insert + Redis LPUSH
    ↓ stt-worker: BRPOP + Whisper + asyncpg INSERT segments
    ↓ GET /api/v1/transcripts/{id} → segments[]
    ↓ GET /api/v1/search?q=cuvant → full-text results
```
