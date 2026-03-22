# MeetRec — Referință Tehnică API
*Pentru dezvoltatorii de client desktop care nu au acces la codebase*

---

## 1. Arhitectură & URL-uri de bază

MeetRec rulează prin Docker Compose. Traficul trece prin Nginx (proxy invers):

| Serviciu | Port extern |
|---|---|
| **Nginx** (reverse proxy) | **80** (HTTP), **443** (HTTPS) |
| **API** (FastAPI, acces direct) | **8080** |
| **PostgreSQL** | 5432 |
| **Redis** | 6379 |

```
Client desktop
  └─► http://localhost:80/api/* → FastAPI
```

**Prefix API**: toate endpoint-urile sunt sub `/api/v1`.

| Mediu | URL de bază |
|---|---|
| Dezvoltare (direct) | `http://localhost:8080` |
| Dezvoltare (prin Nginx) | `http://localhost:80` |
| Producție | `https://meeting-transcriber.local` |

Exemplu complet: `http://localhost:8080/api/v1/auth/login`

Nginx acceptă fișiere audio de până la **600 MB** (`client_max_body_size 600M`).

---

## 2. Autentificare

### 2.1 Flux JWT

```
POST /api/v1/auth/login  { username, password }
→ 200 OK  { access_token, token_type: "bearer", expires_in: 28800 }

# Toate request-urile ulterioare:
Authorization: Bearer <access_token>
```

- Algoritm: **HS256**, stateless (fără sesiuni server-side)
- Durată implicită: **8 ore** (28 800 secunde), configurabilă prin env `JWT_EXPIRE_MINUTES`
- La 401 → șterge token-ul, redirecționează la login
- Logout este **client-side only** (token-ul rămâne tehnic valid până la expirare)

### 2.2 Claims JWT

| Claim | Tip | Exemplu |
|---|---|---|
| `sub` | `string` (UUID) | ID-ul utilizatorului |
| `exp` | `integer` | Unix timestamp expirare |

### 2.3 Token pe endpoint-ul audio

`GET /recordings/{id}/audio` acceptă token-ul **exclusiv** prin query param `?token=<jwt>`, nu prin header `Authorization`. Aceasta este o decizie de design intenționată (compatibilitate cu `<audio src="...">` din browsere). Clientul desktop **poate folosi același mecanism**.

### 2.4 Forțarea schimbării parolei

Dacă `must_change_password: true` în răspunsul `/auth/me`, utilizatorul **trebuie** să apeleze `/auth/change-password-first-login` înainte de a accesa alte funcționalități.

### 2.5 Rate Limiting (per IP)

| Endpoint | Limită |
|---|---|
| `POST /auth/login` | 5 req/minut |
| `GET /search/` | 60 req/minut |
| `GET /search/semantic` | 30 req/minut |
| `GET /export/recording/{id}` | 20 req/oră |

Depășire → `429 Too Many Requests`

---

## 3. Roluri și permisiuni

| Rol | Valoare | Descriere |
|---|---|---|
| Administrator | `"admin"` | Acces complet |
| Operator | `"operator"` | Upload, vizualizare, editare înregistrări; nu gestionează utilizatori |
| Participant | `"participant"` | Read-only; vede **doar** înregistrările la care a fost legat explicit de un admin |

### Matrice acces

| Operație | Admin | Operator | Participant |
|---|---|---|---|
| `GET /auth/me`, logout, schimbare parolă | ✅ | ✅ | ✅ |
| `GET /recordings/` | ✅ toate | ✅ toate | ✅ doar ale sale |
| `GET /recordings/{id}` | ✅ | ✅ | ✅ doar ale sale |
| `PATCH /recordings/{id}` | ✅ | ✅ | ❌ 403 |
| `DELETE /recordings/{id}` | ✅ | ❌ 403 | ❌ 403 |
| `GET /recordings/{id}/audio` | ✅ | ✅ | ✅ doar ale sale |
| `GET/POST/DELETE /recordings/{id}/participants` | ✅ | ❌ 403 | ❌ 403 |
| `POST /inbox/upload` | ✅ | ✅ | ✅ |
| `GET /transcripts/recording/{id}` | ✅ | ✅ | ✅ |
| `POST /transcripts/recording/{id}/retry` | ✅ | ✅ | ✅ |
| `GET /search/*` | ✅ toate | ✅ toate | ✅ doar ale sale |
| `GET /export/recording/{id}` | ✅ | ✅ | ✅ |
| `GET/POST/PATCH/DELETE /users/*` | ✅ | ❌ 403 | ❌ 403 |
| `GET /audit-logs` | ✅ | ❌ 403 | ❌ 403 |
| `GET /health` | ✅ (fără auth) | ✅ | ✅ |

**Regulă participant**: poate vedea o înregistrare **dacă și numai dacă** (1) un admin l-a legat explicit și (2) înregistrarea a fost creată *după* crearea contului participantului.

---

## 4. Enum-uri și constante

### RecordingStatus
```
"uploaded"      — fișier primit, neprelucrat încă
"validating"    — serviciul Ingest validează fișierul
"queued"        — în coada Redis, așteaptă STT worker
"transcribing"  — modelul Whisper transcrie activ
"completed"     — transcriere finalizată cu succes
"failed"        — eroare la procesare (vezi câmpul error_message)
"archived"      — arhivat, inactiv
```

### TranscriptStatus
```
"pending" | "processing" | "completed" | "failed" | "cancelled"
```

### AudioFormat
```
"wav" | "mp3" | "m4a" | "ogg" | "flac" | "webm" | "unknown"
```

### UserRole
```
"admin" | "operator" | "participant"
```

### AuditAction
```
"CREATE" | "UPDATE" | "UPLOAD" | "VIEW" | "SEARCH" | "EXPORT" |
"DELETE" | "TRANSCRIBE" | "LOGIN" | "RETENTION_DELETE" | "SEMANTIC_SEARCH"
```

---

## 5. Toate endpoint-urile REST

### 5.1 Autentificare — `/api/v1/auth`

---

#### `POST /api/v1/auth/login`
**Auth**: Nu | **Rate limit**: 5/minut

**Request body** (`application/json`):
```json
{
  "username": "john_doe",
  "password": "mypassword123"
}
```

**Response 200**:
```json
{
  "access_token": "eyJhbGci...",
  "token_type": "bearer",
  "expires_in": 28800
}
```

| Câmp | Tip | Note |
|---|---|---|
| `access_token` | `string` | JWT |
| `token_type` | `string` | Întotdeauna `"bearer"` |
| `expires_in` | `integer` | Secunde până la expirare (implicit: 28800 = 8h) |

Actualizează și câmpul `last_login` pe utilizator.

**Erori**: `401` credențiale greșite, `429` rate limit depășit

---

#### `POST /api/v1/auth/logout`
**Auth**: Da (orice rol) | **Body**: gol

**Response 200**:
```json
{ "message": "Deconectat cu succes." }
```

> Deoarece JWT este stateless, logout-ul semnalează doar clientul să elimine token-ul. Token-ul rămâne tehnic valid până la expirare.

---

#### `GET /api/v1/auth/me`
**Auth**: Da (orice rol)

**Response 200**:
```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "username": "john_doe",
  "email": "john@example.com",
  "full_name": "John Doe",
  "is_active": true,
  "is_admin": false,
  "is_participant": false,
  "role": "operator",
  "must_change_password": false
}
```

---

#### `POST /api/v1/auth/change-password-first-login`
**Auth**: Da (orice rol)

**Request body** (`application/json`):
```json
{
  "current_password": "oldpass",
  "new_password": "newpassword123"
}
```

| Câmp | Tip | Validare |
|---|---|---|
| `current_password` | `string` | min 1 caracter |
| `new_password` | `string` | min 8, max 255 caractere |

**Response 200**:
```json
{ "message": "Parola a fost schimbată cu succes." }
```

**Erori**: `400` parolă curentă greșită sau parolă nouă identică cu cea veche

---

### 5.2 Înregistrări — `/api/v1/recordings`

Toate endpoint-urile necesită autentificare. Participanții sunt filtrați la înregistrările lor.

---

#### `GET /api/v1/recordings/`
**Auth**: Da (participanții văd doar pe ale lor)

**Query params**:

| Param | Tip | Default | Note |
|---|---|---|---|
| `page` | integer | `1` | min 1 |
| `page_size` | integer | `20` | 1–100 |
| `status` | string | null | filtrare după RecordingStatus |
| `search` | string | null | căutare în titlu |
| `sort_by` | string | `"created_at"` | câmpul de sortare |
| `sort_desc` | boolean | `true` | ordine descrescătoare |

**Response 200** (`PaginatedRecordings`):
```json
{
  "items": [
    {
      "id": "3fa85f64-...",
      "title": "Ședință Consiliu Ianuarie 2024",
      "meeting_date": "2024-01-15",
      "audio_format": "mp3",
      "duration_formatted": "01:23:45",
      "file_size_mb": 45.2,
      "status": "completed",
      "created_at": "2024-01-15T14:30:00Z",
      "transcript_status": "completed"
    }
  ],
  "total": 150,
  "page": 1,
  "page_size": 20,
  "pages": 8,
  "has_next": true,
  "has_prev": false
}
```

---

#### `GET /api/v1/recordings/{recording_id}`
**Auth**: Da (participanții văd doar ale lor) | **Path param**: UUID

**Response 200** (`RecordingResponse`):
```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "title": "Ședință Consiliu Ianuarie 2024",
  "description": "Discuție buget T1",
  "meeting_date": "2024-01-15",
  "location": "Sala de Conferințe A",
  "participants": ["Alice Smith", "Bob Jones"],
  "original_filename": "sedinta_ian15.mp3",
  "file_size_bytes": 47382467,
  "audio_format": "mp3",
  "duration_seconds": 5025,
  "duration_formatted": "01:23:45",
  "file_size_mb": 45.2,
  "status": "completed",
  "error_message": null,
  "created_at": "2024-01-15T14:30:00Z",
  "updated_at": "2024-01-15T15:10:00Z",
  "retain_until": null,
  "transcript": {
    "id": "abc12345-...",
    "status": "completed",
    "word_count": 8321,
    "completed_at": "2024-01-15T15:09:00Z"
  },
  "resolved_participants": [
    {
      "user_id": "user-uuid-...",
      "username": "alice_smith",
      "full_name": "Alice Smith",
      "email": "alice@example.com",
      "linked_at": "2024-01-16T09:00:00Z"
    }
  ]
}
```

| Câmp | Tip | Note |
|---|---|---|
| `participants` | `string[]` | Numele brute din metadate (nu conturi legate) |
| `resolved_participants` | `ParticipantUserInfo[]` | Conturi de utilizatori legate explicit de un admin |
| `error_message` | `string\|null` | Populat când `status == "failed"` |
| `retain_until` | `string\|null` | `"YYYY-MM-DD"` — data ștergerii automate |

> **Notă de securitate**: câmpul `file_path` (calea pe serverul de fișiere) **nu este niciodată** inclus în răspunsuri API.

**Erori**: `404` înregistrare inexistentă sau participant fără acces

---

#### `PATCH /api/v1/recordings/{recording_id}`
**Auth**: Da — **operator sau admin** (participant → 403)

**Request body** (toate câmpurile opționale):
```json
{
  "title": "Titlu actualizat",
  "description": "Descriere actualizată",
  "meeting_date": "2024-01-20",
  "location": "Sala Mare",
  "participants": ["Alice Smith", "Bob Jones", "Carol White"]
}
```

| Câmp | Tip | Validare |
|---|---|---|
| `title` | `string\|null` | min 3, max 500 |
| `description` | `string\|null` | — |
| `meeting_date` | `string\|null` | `"YYYY-MM-DD"` |
| `location` | `string\|null` | — |
| `participants` | `string[]\|null` | Array de nume |

**Response 200**: obiect `RecordingResponse` complet (ca la GET)

---

#### `DELETE /api/v1/recordings/{recording_id}`
**Auth**: Da — **admin only**

**Response 204 No Content**

**Erori**: `403` (nu admin), `404`, `500` (eroare sistem de fișiere)

---

#### `GET /api/v1/recordings/{recording_id}/audio`
**Auth**: **obligatoriu prin `?token=<jwt>`** — NU prin header `Authorization`!

> Aceasta este o decizie de design intenționată. Clientul desktop trebuie să atașeze token-ul ca query param.

**Query params**:

| Param | Tip | Obligatoriu |
|---|---|---|
| `token` | `string` | ✅ |

**Response 200**: stream binar audio
**Content-Type**: detectat automat (`audio/mpeg`, `audio/wav`, etc.)
**Header**: `Content-Disposition: attachment; filename="<filename>"`

**Erori**: `401` token lipsă/invalid, `403` participant fără acces la înregistrare, `404` fișier negăsit pe disc

---

#### `GET /api/v1/recordings/{recording_id}/participants`
**Auth**: Da — **admin only**

**Response 200** (array de `ParticipantUserInfo`):
```json
[
  {
    "user_id": "3fa85f64-...",
    "username": "alice_smith",
    "full_name": "Alice Smith",
    "email": "alice@example.com",
    "linked_at": "2024-01-16T09:00:00Z"
  }
]
```

---

#### `POST /api/v1/recordings/{recording_id}/participants`
**Auth**: Da — **admin only**

Leagă un cont utilizator (cu `role == "participant"`) la o înregistrare, acordându-i acces.

**Request body** (`application/json`):
```json
{ "user_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6" }
```

**Response 201**:
```json
{ "recording_id": "3fa85f64-...", "user_id": "abc12345-..." }
```

**Erori**: `404` (înregistrare sau user inexistent/inactiv), `409` (deja legat), `422` (userul nu are rol participant)

---

#### `DELETE /api/v1/recordings/{recording_id}/participants/{user_id}`
**Auth**: Da — **admin only**

**Path params**: `recording_id` (UUID), `user_id` (UUID)

**Response 204 No Content**

**Erori**: `404` înregistrare negăsită sau legătura nu există

---

### 5.3 Upload fișier — `/api/v1/inbox`

#### `POST /api/v1/inbox/upload`
**Auth**: Da (orice rol)

Procesare **asincronă** — API-ul returnează `202 Accepted` imediat; înregistrarea apare în listă după ce Ingest Service-ul o procesează.

**Request**: `multipart/form-data`

| Câmp | Tip | Obligatoriu | Note |
|---|---|---|---|
| `file` | fișier | ✅ | Fișier audio |
| `title` | string | ❌ | Titlul ședinței |
| `meeting_date` | string | ❌ | `"YYYY-MM-DD"` |
| `description` | string | ❌ | — |
| `participants` | string | ❌ | Nume separate prin virgulă: `"Alice, Bob"` |
| `location` | string | ❌ | — |

**Formate acceptate**: `MP3`, `WAV`, `M4A`, `OGG`, `FLAC`, `WEBM`
**Dimensiune maximă**: **500 MB** (API) / **600 MB** (Nginx)

**Response 202**:
```json
{
  "message": "Fișierul a fost primit și va fi procesat în scurt timp. Înregistrarea va apărea în listă după validare.",
  "filename": "sedinta_ian15.mp3"
}
```

**Erori**: `400` fișier fără nume, `500` eroare scriere pe disc

> **Important**: un `202` nu garantează că fișierul va fi acceptat. Ingest Service-ul poate respinge ulterior fișiere invalide sau duplicate (același hash SHA256).

---

### 5.4 Transcrieri — `/api/v1/transcripts`

#### `GET /api/v1/transcripts/recording/{recording_id}`
**Auth**: Da (orice rol)

**Response 200** (`TranscriptResponse`):
```json
{
  "id": "abc12345-5717-4562-b3fc-2c963f66afa6",
  "recording_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status": "completed",
  "language": "ro",
  "model_used": "whisper-medium",
  "word_count": 8321,
  "confidence_avg": 0.923,
  "processing_time_sec": 180,
  "created_at": "2024-01-15T14:35:00Z",
  "completed_at": "2024-01-15T15:09:00Z",
  "full_text": "Bună ziua doamnelor și domnilor...",
  "segments": [
    {
      "id": "seg-uuid-...",
      "segment_index": 0,
      "start_time": 0.0,
      "end_time": 4.5,
      "text": "Bună ziua doamnelor și domnilor.",
      "confidence": 0.98,
      "speaker_id": "SPEAKER_00",
      "language": "ro"
    }
  ]
}
```

**Câmpuri `SegmentResponse`**:

| Câmp | Tip | Note |
|---|---|---|
| `segment_index` | `integer` | 0-based, ordonat ASC |
| `start_time` | `float` | Secunde (ex: `12.500`) |
| `end_time` | `float` | Secunde |
| `text` | `string` | Fraza rostită |
| `confidence` | `float\|null` | `0.0` – `1.0` |
| `speaker_id` | `string\|null` | `"SPEAKER_00"`, `"SPEAKER_01"` (diarizare) |
| `language` | `string\|null` | Limba detectată pentru segment |

**Erori**: `404` transcriere inexistentă sau neprocesată

---

#### `POST /api/v1/transcripts/recording/{recording_id}/retry`
**Auth**: Da

Re-coadă un job de transcriere eșuat. Funcționează **doar dacă** `status == "failed"`.

**Response 200**:
```json
{ "message": "Job retrimat cu succes.", "recording_id": "3fa85f64-..." }
```

**Erori**: `400` înregistrare inexistentă sau status != "failed"

---

### 5.5 Căutare — `/api/v1/search`

Participanții văd doar rezultate din înregistrările lor.

---

#### `GET /api/v1/search/`
**Auth**: Da | **Rate limit**: 60/minut

Căutare full-text (PostgreSQL TSVECTOR, stemmer românesc + extensia `unaccent`).

**Query params**:

| Param | Tip | Obligatoriu | Default | Note |
|---|---|---|---|---|
| `q` | string | ✅ | — | min 2 caractere |
| `limit` | integer | ❌ | `20` | 1–100 |
| `offset` | integer | ❌ | `0` | paginare |
| `language` | string | ❌ | null | `"ro"` sau `"en"` |

**Response 200** (`SearchResponse`):
```json
{
  "query": "buget 2024",
  "results": [
    {
      "recording_id": "3fa85f64-...",
      "recording_title": "Ședință Consiliu Ianuarie 2024",
      "meeting_date": "2024-01-15",
      "segment_id": "seg-uuid-...",
      "start_time": 142.5,
      "end_time": 156.0,
      "text": "Discutăm acum bugetul pentru 2024.",
      "headline": "Discutăm acum <b>bugetul</b> pentru <b>2024</b>.",
      "rank": 0.0759
    }
  ],
  "total_results": 42,
  "offset": 0,
  "limit": 20,
  "pages": 3,
  "search_time_ms": 18
}
```

`headline` conține HTML cu termenul găsit învelit în `<b>`.
`rank` = scor relevanță PostgreSQL FTS (mai mare = mai relevant).

---

#### `GET /api/v1/search/semantic`
**Auth**: Da | **Rate limit**: 30/minut

Căutare semantică prin vectori (embeddings 384-dim, model `paraphrase-multilingual-MiniLM-L12-v2`). Găsește conținut relevant conceptual, fără potrivire exactă de cuvinte.

**Query params**:

| Param | Tip | Obligatoriu | Default |
|---|---|---|---|
| `q` | string | ✅ | — |
| `limit` | integer | ❌ | `20` |

**Response 200** (`SemanticSearchResponse`):
```json
{
  "query": "discuție despre finanțarea proiectului",
  "results": [
    {
      "recording_id": "3fa85f64-...",
      "recording_title": "Ședință Consiliu Ianuarie 2024",
      "meeting_date": "2024-01-15",
      "segment_id": "seg-uuid-...",
      "start_time": 142.5,
      "end_time": 156.0,
      "text": "Alocarea bugetului pentru proiectul de infrastructură.",
      "similarity": 0.87
    }
  ],
  "total_results": 15,
  "limit": 20,
  "search_time_ms": 45
}
```

`similarity`: `0.0`–`1.0` (similaritate cosinus; 1.0 = identic semantic).

**Erori**: `503` dacă modelul semantic nu s-a încărcat încă.

---

#### `GET /api/v1/search/combined`
**Auth**: Da

Rulează ambele tipuri de căutare (FTS + semantic) și combină rezultatele, deduplicând segmentele găsite de ambele.

**Query params**: `q` (obligatoriu), `limit` (opțional, default 20)

**Response 200** (`CombinedSearchResponse`):
```json
{
  "query": "buget proiect",
  "results": [
    {
      "recording_id": "...",
      "recording_title": "Ședință Consiliu Ianuarie 2024",
      "meeting_date": "2024-01-15",
      "segment_id": "...",
      "start_time": 142.5,
      "end_time": 156.0,
      "text": "Alocarea bugetului pentru proiectul de infrastructură.",
      "headline": "Alocarea <b>bugetului</b> pentru <b>proiect</b>.",
      "rank": 0.0759,
      "similarity": 0.87,
      "source": "both"
    }
  ],
  "total_results": 20,
  "fts_count": 12,
  "semantic_count": 14,
  "both_count": 6,
  "search_time_ms": 62
}
```

| Câmp | Tip | Note |
|---|---|---|
| `source` | `"fts" \| "semantic" \| "both"` | Care metodă a găsit segmentul |
| `rank` | `float\|null` | Scor FTS (null dacă doar semantic) |
| `similarity` | `float\|null` | Similaritate semantică (null dacă doar FTS) |
| `fts_count` | `integer` | Segmente găsite doar de FTS |
| `semantic_count` | `integer` | Segmente găsite doar de semantic |
| `both_count` | `integer` | Segmente găsite de ambele metode |

---

### 5.6 Export — `/api/v1/export`

#### `GET /api/v1/export/recording/{recording_id}`
**Auth**: Da | **Rate limit**: 20/oră

**Query params**:

| Param | Tip | Default | Valori permise |
|---|---|---|---|
| `format` | string | `"txt"` | `"txt"`, `"pdf"`, `"docx"` |

**Response 200**: fișier binar pentru descărcare

| Format | Content-Type |
|---|---|
| `txt` | `text/plain; charset=utf-8` |
| `pdf` | `application/pdf` |
| `docx` | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` |

**Header răspuns**: `Content-Disposition: attachment; filename*=UTF-8''<titlu>.<ext>`

Exemplu format TXT:
```
TRANSCRIERE: Ședință Consiliu Ianuarie 2024
Data ședinței: 2024-01-15
Durată: 01:23:45
Limbă: ro
Exportat: 15.01.2024 14:30

============================================================

[00:00]  Bună ziua doamnelor și domnilor.
[02:22]  Discutăm acum bugetul pentru 2024.
```

**Erori**: `404` înregistrare negăsită sau transcriere incompletă, `429` rate limit depășit

---

### 5.7 Jurnale Audit — `/api/v1/audit-logs`

#### `GET /api/v1/audit-logs`
**Auth**: Da — **admin only**

**Query params**: `page` (default 1), `page_size` (default 20, max 100)

**Response 200** (`PaginatedAuditLogs`):
```json
{
  "items": [
    {
      "id": "log-uuid-...",
      "timestamp": "2024-01-15T14:30:00Z",
      "user_id": "3fa85f64-...",
      "user_ip": "192.168.1.100",
      "user_username": "john_doe",
      "user_email": "john@example.com",
      "action": "VIEW",
      "resource_type": "transcript",
      "resource_id": "abc12345-...",
      "success": true,
      "details": { "query": "buget 2024", "total": 5 }
    }
  ],
  "total": 8432,
  "page": 1,
  "page_size": 20,
  "pages": 422
}
```

Rezultatele sunt ordonate descrescător după `timestamp`.

---

### 5.8 Utilizatori — `/api/v1/users`

Toate endpoint-urile necesită rol **admin**.

---

#### `GET /api/v1/users`

**Query params**:

| Param | Tip | Default | Note |
|---|---|---|---|
| `page` | integer | `1` | — |
| `page_size` | integer | `20` | max 100 |
| `search` | string | null | Caută în username, email, full_name |
| `include_inactive` | boolean | `false` | Include utilizatori dezactivați |

**Response 200** (`PaginatedUsers`):
```json
{
  "items": [
    {
      "id": "3fa85f64-...",
      "username": "john_doe",
      "email": "john@example.com",
      "full_name": "John Doe",
      "is_active": true,
      "is_admin": false,
      "role": "operator",
      "must_change_password": false,
      "last_login": "2024-01-15T14:30:00Z",
      "created_at": "2023-08-01T10:00:00Z"
    }
  ],
  "total": 25,
  "page": 1,
  "page_size": 20,
  "pages": 2
}
```

---

#### `POST /api/v1/users`

**Request body** (`application/json`):
```json
{
  "username": "new_operator",
  "email": "operator@company.com",
  "full_name": "New Operator",
  "password": "securepassword123",
  "role": "operator"
}
```

| Câmp | Tip | Obligatoriu | Validare |
|---|---|---|---|
| `username` | string | ✅ | min 3, max 100 |
| `email` | string | ✅ | min 5, max 255, conține `@` |
| `full_name` | string | ❌ | max 255 |
| `password` | string | ✅ | min 8, max 255 |
| `role` | string | ❌ | default `"operator"`; valori: `"admin"`, `"operator"`, `"participant"` |

**Response 201**: obiect `UserResponse`

**Erori**: `409` username sau email deja există

---

#### `GET /api/v1/users/suggest`
Autocompletare utilizatori (max 10 rezultate). Util pentru legarea participanților la înregistrări.

**Query params**:

| Param | Tip | Obligatoriu | Note |
|---|---|---|---|
| `q` | string | ✅ | min 1, max 100; caută în full_name, username, email |
| `role` | string | ❌ | filtrare opțională după rol |

**Response 200** (array de `UserSuggest`):
```json
[
  {
    "id": "3fa85f64-...",
    "username": "alice_smith",
    "full_name": "Alice Smith",
    "email": "alice@example.com",
    "role": "participant"
  }
]
```

Returnează doar utilizatori activi.

---

#### `GET /api/v1/users/{user_id}`
**Path param**: `user_id` — UUID

**Response 200**: obiect `UserResponse` complet (ca în lista de mai sus)

**Erori**: `404` utilizator negăsit

---

#### `PATCH /api/v1/users/{user_id}`
Toate câmpurile opționale (semantică PATCH).

**Request body** (`application/json`):
```json
{
  "email": "new_email@company.com",
  "full_name": "Nume Actualizat",
  "is_active": false,
  "role": "participant"
}
```

| Câmp | Tip | Validare |
|---|---|---|
| `email` | `string\|null` | min 5, max 255, conține `@` |
| `full_name` | `string\|null` | max 255 |
| `is_active` | `boolean\|null` | — |
| `role` | `string\|null` | `"admin"`, `"operator"`, `"participant"` |

**Regulă**: un admin nu poate schimba propriul rol sau dezactiva propriul cont.

**Response 200**: obiect `UserResponse`

**Erori**: `403` acțiune interzisă, `404` negăsit, `409` conflict email

---

#### `DELETE /api/v1/users/{user_id}`
**Response 204 No Content**

Un admin nu poate șterge propriul cont → `403`.

---

### 5.9 Sănătate sistem

#### `GET /health`
**Auth**: Nu este necesar

**Response 200**:
```json
{
  "status": "healthy",
  "service": "meeting-transcriber-api",
  "version": "1.0.0",
  "environment": "development"
}
```

---

## 6. Pipeline asincron de procesare (după upload)

```
Client desktop
  │
  ▼  POST /api/v1/inbox/upload  (multipart/form-data)
  │
  ▼  API → salvează fișier în /data/inbox/<filename>
  │         + sidecar: /data/inbox/<filename>.meetrec-meta.json
  │
  ▼  Răspuns imediat: 202 Accepted
  │
  ▼  [Ingest Service — rulează independent]
  │    1. Detectează fișier nou (inotify/watchdog)
  │    2. Citește sidecar JSON (titlu, dată, etc.)
  │    3. Validează: format, dimensiune ≤ 500 MB, integritate audio
  │    4. Verifică hash SHA256 — respinge dacă fișierul există deja
  │    5. Mută fișierul în /data/processed/<an>/<lună>/<uuid>.<ext>
  │    6. Creează înregistrare în PostgreSQL cu status="queued"
  │    7. Publică job în coada Redis "transcription_jobs"
  │
  ▼  [STT Worker — rulează independent, model Whisper]
  │    1. Preia job din Redis
  │    2. Transcrie audio → creează transcript + segmente în DB
  │    3. Actualizează status înregistrare: "completed" sau "failed"
  │
  ▼  [Search Indexer — rulează independent]
       1. Generează embeddings 384-dim pentru fiecare segment
       2. Stochează în coloana `embedding` (pgvector, HNSW index)
```

**Pattern de polling recomandat**: după upload, sondează `GET /recordings/` (sau `GET /recordings/{id}`) până când înregistrarea apare cu un status diferit de `"uploaded"`.

Progresie tipică status:
```
uploaded → validating → queued → transcribing → completed
                                              └─→ failed
```

---

## 7. WebSocket / SSE

**Nu există.** API-ul este pur REST/HTTP. Actualizările de status se obțin **exclusiv prin polling**.

---

## 8. Format erori

Toate erorile returnează JSON standard FastAPI:
```json
{ "detail": "Descriere eroare în română." }
```

Erori de validare a request-ului (`422 Unprocessable Entity`):
```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "username"],
      "msg": "Field required",
      "input": {}
    }
  ]
}
```

### Coduri HTTP

| Cod | Semnificație | Când apare |
|---|---|---|
| `200` | OK | GET, PATCH reușit |
| `201` | Created | POST care creează o resursă |
| `202` | Accepted | Upload acceptat (procesare asincronă urmează) |
| `204` | No Content | DELETE reușit |
| `400` | Bad Request | Eroare logică de business (ex: parolă greșită) |
| `401` | Unauthorized | Token lipsă, invalid sau expirat |
| `403` | Forbidden | Token valid dar rol insuficient |
| `404` | Not Found | Resursa nu există (sau participant fără acces) |
| `409` | Conflict | Duplicat (username, email, participant deja legat) |
| `422` | Unprocessable Entity | Validare body eșuată |
| `429` | Too Many Requests | Rate limit depășit |
| `500` | Internal Server Error | Eroare neașteptată pe server |
| `503` | Service Unavailable | Modelul semantic nu s-a încărcat încă |

---

## 9. CORS

| Mediu | Origini permise |
|---|---|
| `development` | `*` (toate originile) |
| `production` | `https://meeting-transcriber.local` |

**Metode permise**: `GET`, `POST`, `PATCH`, `DELETE`, `OPTIONS`
**Headere permise**: `Content-Type`, `Authorization`
**Credentials**: `true` (cookies permise)

---

## 10. Schema bazei de date (sumar)

### `recordings`
| Coloană | Tip | Note |
|---|---|---|
| `id` | `UUID` PK | Auto-generat |
| `title` | `VARCHAR(500)` | NOT NULL |
| `description` | `TEXT` | nullable |
| `meeting_date` | `DATE` | NOT NULL |
| `location` | `VARCHAR(255)` | nullable |
| `participants` | `TEXT[]` | Array PostgreSQL de nume brute |
| `original_filename` | `VARCHAR(500)` | NOT NULL |
| `file_path` | `VARCHAR(1000)` | Cale server — **niciodată** expusă în API |
| `file_size_bytes` | `BIGINT` | NOT NULL |
| `file_hash_sha256` | `CHAR(64)` | UNIQUE — previne upload-uri duplicate |
| `audio_format` | `audio_format` | ENUM |
| `duration_seconds` | `INTEGER` | nullable |
| `status` | `recording_status` | ENUM |
| `error_message` | `TEXT` | nullable |
| `created_at` | `TIMESTAMPTZ` | DEFAULT NOW() |
| `updated_at` | `TIMESTAMPTZ` | Auto-actualizat prin trigger |
| `retain_until` | `DATE` | nullable; politică ștergere automată |

### `transcripts`
| Coloană | Tip | Note |
|---|---|---|
| `id` | `UUID` PK | |
| `recording_id` | `UUID` FK → recordings | UNIQUE (relație 1:1) |
| `status` | `transcription_status` ENUM | |
| `language` | `VARCHAR(10)` | `"ro"`, `"en"`, `"ro-en"` |
| `model_used` | `VARCHAR(100)` | ex: `"whisper-medium"` |
| `word_count` | `INTEGER` | |
| `confidence_avg` | `DECIMAL(4,3)` | 0.000–1.000 |
| `processing_time_sec` | `INTEGER` | |
| `created_at` | `TIMESTAMPTZ` | |
| `completed_at` | `TIMESTAMPTZ` | nullable |

### `transcript_segments`
| Coloană | Tip | Note |
|---|---|---|
| `id` | `UUID` PK | |
| `transcript_id` | `UUID` FK → transcripts | |
| `segment_index` | `INTEGER` | 0-based, UNIQUE per transcriere |
| `start_time` | `DECIMAL(10,3)` | Secunde, ex: `12.500` |
| `end_time` | `DECIMAL(10,3)` | Secunde |
| `text` | `TEXT` | NOT NULL |
| `confidence` | `DECIMAL(4,3)` | 0.000–1.000 |
| `speaker_id` | `VARCHAR(50)` | ex: `"SPEAKER_00"` |
| `language` | `VARCHAR(10)` | |
| `embedding` | `vector(384)` | Embedding semantic (pgvector, HNSW indexed) |

### `users`
| Coloană | Tip | Note |
|---|---|---|
| `id` | `UUID` PK | |
| `username` | `VARCHAR(100)` | UNIQUE |
| `email` | `VARCHAR(255)` | UNIQUE |
| `password_hash` | `VARCHAR(255)` | Hash bcrypt — **niciodată** expus în API |
| `full_name` | `VARCHAR(255)` | nullable |
| `is_active` | `BOOLEAN` | DEFAULT TRUE |
| `role` | `VARCHAR(20)` | `"admin"`, `"operator"`, `"participant"` |
| `must_change_password` | `BOOLEAN` | DEFAULT FALSE |
| `created_at` | `TIMESTAMPTZ` | |
| `last_login` | `TIMESTAMPTZ` | nullable |

### `recording_participants`
| Coloană | Tip | Note |
|---|---|---|
| `recording_id` | `UUID` FK | PK compozit |
| `user_id` | `UUID` FK | PK compozit |
| `linked_at` | `TIMESTAMPTZ` | DEFAULT NOW() |
| `linked_by` | `UUID` FK | Admin-ul care a creat legătura |

### `audit_logs`
| Coloană | Tip | Note |
|---|---|---|
| `id` | `UUID` PK | |
| `timestamp` | `TIMESTAMPTZ` | Indexat DESC |
| `user_id` | `UUID` | nullable (null = neautentificat) |
| `user_ip` | `INET` | IPv4 sau IPv6 |
| `user_agent` | `VARCHAR(500)` | |
| `action` | `audit_action` ENUM | |
| `resource_type` | `VARCHAR(100)` | ex: `"recording"`, `"transcript"` |
| `resource_id` | `UUID` | |
| `details` | `JSONB` | Context adițional flexibil |
| `success` | `BOOLEAN` | |

---

## 11. Note importante pentru clientul desktop

1. **Documentație interactivă** (`/docs` Swagger UI, `/redoc`) disponibilă **doar în mediul de development** (`APP_ENV=development`). Dezactivată în producție din motive de securitate.

2. **Upload duplicate**: dacă trimiți același fișier audio de două ori (același hash SHA256), al doilea este respins silențios de Ingest Service, deși API-ul returnează `202` pentru ambele.

3. **Audio endpoint — token obligatoriu în query param**: `GET /recordings/{id}/audio?token=<jwt>` — header-ul `Authorization` nu funcționează pe acest endpoint.

4. **Căutare semantică cu latență**: după finalizarea transcrierii, segmentele nu sunt imediat disponibile în căutarea semantică. Search Indexer-ul generează embedding-urile asincron — poate dura câteva secunde/minute pentru fișiere mari.

5. **Limbă FTS**: căutarea full-text folosește stemmer-ul românesc PostgreSQL cu extensia `unaccent` — diacriticele și formele flexionare sunt normalizate automat. Căutând `"doamna"` se găsesc și `"doamnelor"`, `"doamnele"` etc.

6. **Parole**: stocate ca hash-uri bcrypt. API-ul nu expune niciodată `password_hash` în niciun răspuns.

7. **Politică de retenție**: câmpul `retain_until` pe înregistrări — un serviciu background (`audit-retention`) șterge automat înregistrările expirate. Retenție implicită: **3 ani (1095 zile)**.

8. **Acces participant — regulă temporală**: chiar dacă un admin leagă un participant la o înregistrare mai veche decât contul participantului, accesul este blocat automat de server.
