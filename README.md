# MeetRec

**Platformă self-hosted de transcriere automată a ședințelor.**
Detectează fișiere audio, le transcrie cu OpenAI Whisper (local, fără cloud) și expune un REST API cu căutare full-text.

> Documentație tehnică detaliată: [technical_docs.md](technical_docs.md)

---

## Ce face

| Funcționalitate | Descriere |
|---|---|
| Ingestie automată | Copiați un fișier audio în `/data/inbox` — se procesează automat |
| Upload web | Interfața web / `POST /api/v1/inbox/upload` — fișierul ajunge în inbox, Ingest preia |
| Speech-to-text | OpenAI Whisper medium (~85% acuratețe pentru română) |
| Căutare full-text | PostgreSQL TSVECTOR + index GIN, returnează snippets cu termenul evidențiat |
| Export transcriere | PDF, DOCX, TXT |
| Autentificare JWT | HS256, 8h expirare, bcrypt hashing |
| Interfață web | React SPA cu player audio sincronizat cu transcrierea |
| Audit log | Fiecare acțiune (upload, vizualizare, căutare, export, ștergere) este înregistrată |
| Retenție | Ștergere automată configurabilă după N zile |
| Monitorizare | Grafana + Loki + Promtail |

---

## Arhitectură

```
Browser / drop-folder
        │
        ▼
  POST /inbox/upload          cp fisier.mp3 data/inbox/
        │                              │
        ▼                              ▼
      API  ──── scrie ────▶  /data/inbox/
                                       │
                               Ingest Service   (validare completă: format,
                                       │         dimensiune, durată, SHA256)
                                       ▼
                                 Redis Queue
                                       │
                               STT Worker (Whisper)
                                       │
                                 PostgreSQL DB
                                       ▲
                                   FastAPI (API)   (CRUD, căutare, export)
                                       ▲
                               Nginx ← Frontend (React)
```

**Regulă fundamentală:** Ingest Service este **singura** cale prin care audio intră în sistem și face toate validările. API-ul nu atinge fișierele audio — doar le depune în inbox.

**Servicii:**

| Serviciu | Tehnologie |
|---|---|
| API | FastAPI + SQLAlchemy async |
| Ingest | watchdog + asyncpg |
| STT Worker | OpenAI Whisper + asyncpg |
| Frontend | React + Vite + TailwindCSS |
| DB | PostgreSQL 15 |
| Queue | Redis 7 |
| Proxy | Nginx 1.25 |
| Monitorizare | Grafana + Loki + Promtail |

---

## Instalare rapidă

**Cerințe:** Docker ≥ 24.0, Docker Compose v2, 6 GB RAM, 6 GB spațiu liber.

```bash
# 1. Clonați repo-ul
git clone <repository-url>
cd meeting-transcriber

# 2. Configurați variabilele de mediu
cp .env.example .env
# Editați .env — setați JWT_SECRET_KEY, POSTGRES_PASSWORD, GRAFANA_ADMIN_PASSWORD

# 3. Creați directorul inbox
mkdir -p data/inbox

# 4. Porniți toate serviciile
docker compose up --build -d

# 5. Verificați
curl http://localhost:8080/health
# → {"status":"healthy", ...}
```

Prima pornire descarcă modelul Whisper medium (~1.5 GB) — poate dura câteva minute.

**UI web:** `http://localhost` (sau portul Nginx configurat)
**API docs:** `http://localhost:8080/docs` (doar în `APP_ENV=development`)
**Grafana:** `http://localhost:3000`

---

## Utilizare

### Drop-folder

```bash
cp sedinta.mp3 data/inbox/
# Ingest Service detectează fișierul, îl validează și îl trimite la transcriere
docker compose logs -f ingest stt-worker
```

### REST API

```bash
# Autentificare
curl -X POST http://localhost:8080/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "parola"}'
# → {"access_token": "eyJ...", "token_type": "bearer"}

export TOKEN="eyJ..."

# Upload fișier audio (ajunge în inbox → Ingest preia automat)
curl -X POST http://localhost:8080/api/v1/inbox/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@sedinta.mp3"
# → 202 Accepted: {"message": "Fișierul a fost primit...", "filename": "sedinta.mp3"}

# Actualizare metadata după ce Ingest creează înregistrarea
curl -X PATCH http://localhost:8080/api/v1/recordings/{id} \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title": "Ședința Consiliului — 15 ian 2024", "meeting_date": "2024-01-15"}'

# Căutare full-text
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8080/api/v1/search?q=buget+2024"

# Export PDF
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8080/api/v1/export/{id}?format=pdf" \
  --output transcriere.pdf
```

---

## Configurare

Toate setările sunt în fișierul `.env`. Variabilele obligatorii:

| Variabilă | Descriere |
|---|---|
| `JWT_SECRET_KEY` | Cheie semnare JWT (min. 32 caractere) |
| `POSTGRES_PASSWORD` | Parolă PostgreSQL |
| `GRAFANA_ADMIN_PASSWORD` | Parolă admin Grafana |
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@postgres:5432/meetrec_db` |

Variabile opționale importante:

| Variabilă | Default | Descriere |
|---|---|---|
| `WHISPER_MODEL` | `medium` | Dimensiune model: `tiny`, `base`, `small`, `medium`, `large` |
| `RETENTION_DAYS` | `1095` | Zile de păstrare înregistrări (3 ani) |
| `APP_ENV` | `development` | `production` dezactivează `/docs` și CORS permisiv |
| `MAX_FILE_SIZE_BYTES` | `524288000` | Limită upload (500 MB) |

---

## Status implementare

| Componentă | Status |
|---|---|
| Ingest Service | ✅ Complet — singura cale de intrare audio |
| STT Worker | ✅ Complet — Whisper medium, română |
| API — CRUD, inbox, căutare, export, auth, audit | ✅ Complet |
| Frontend React | ✅ Complet — upload, listă, detaliu, căutare, admin |
| Schema PostgreSQL | ✅ Completă |
| Monitorizare Grafana/Loki | ✅ Configurată |
| Audit-Retention Service | ⏳ Dockerfile gata, sursă neimplementată |
| Search Indexer Service | ⏳ Placeholder |
| Migrări Alembic | ⏳ Neimplementate |

---

## Licență

Proiect intern. Toate drepturile rezervate.
