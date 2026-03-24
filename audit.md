# MeetRec — Audit de Securitate, Arhitectură și Clean Code

**Data:** 24 Martie 2026
**Revizie:** Rev. 4
**Analist:** Claude Code (claude-sonnet-4-6)

---

## EXECUTIVE SUMMARY

| Categorie | CRITIC | HIGH | MEDIUM | LOW |
|---|---|---|---|---|
| Securitate | 1 | 5 | 10 | 2 |
| Arhitectură | 0 | 2 | 5 | 1 |
| Clean Code | 0 | 0 | 6 | 7 |

---

## 1. SECURITATE

### CRITIC

**SEC-1: JWT Token în Query String**
- **Fișier:** `services/api/src/routers/recordings.py:173` + `middleware/auth.py:91`
- Tokenul audio apare ca `?token=eyJ...` în URL → logat de nginx, vizibil în browser history, transmis în Referer header
- **Fix:** Streaming-ul audio ar trebui să citească tokenul din `Authorization: Bearer`, nu din query param

### HIGH

**SEC-2: SQL Injection în vector embedding**
- **Fișier:** `services/api/src/services/search_service.py:178`
```python
# Vector interpolat direct în SQL string — dacă search-indexer e compromis:
vector_literal = "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"
sql = text(f"... '{vector_literal}'::vector ...")  # PERICULOS
```
- **Fix:** Parametrizează vectorul, nu string interpolation.

**SEC-3: No filename sanitization la upload**
- **Fișier:** `services/api/src/routers/inbox.py:85-150`
```python
dest = inbox_path / file.filename  # filename nevalidat! ../../etc/passwd.mp3
```
- **Fix:** `filename = f"{uuid.uuid4()}{Path(file.filename).suffix}"`

**SEC-4: Logging date sensibile**
- **Fișier:** `services/api/src/middleware/audit.py:67`, `routers/search.py:71`
- Query-ul de căutare e logat integral în audit_logs → `{"query": "parola_mea_secreta"}`
- User-Agent (fingerprint) e logat
- **Fix:** Trunchiază query-urile în logs, redactează PII

**SEC-5: Parola reset fără notificare**
- **Fișier:** `services/api/src/routers/users.py:128`
- Admin poate reseta parola oricărui user fără email notification → zero audit trail pentru abuz
- **Fix:** Trimite email de notificare la user înainte de reset

**SEC-6: Path traversal potențial via database path**
- **Fișier:** `services/api/src/routers/recordings.py:202`
- Dacă ingest scrie un symlink, `Path.resolve()` check poate fi bypassat
- **Fix:** Stochează fișierele cu UUID generate, nu paths user-controlled

### MEDIUM

| ID | Descriere | Fișier |
|---|---|---|
| SEC-7 | No HTTPS enforcement în nginx | `nginx/nginx.conf` |
| SEC-8 | Security headers lipsă (X-Frame-Options, CSP, HSTS) | `nginx/nginx.conf` |
| SEC-9 | CORS `allow_origins=["*"]` în development | `api/src/main.py:110` |
| SEC-10 | No account lockout după failed login (5/min e prea permisiv) | `api/src/routers/auth.py:36` |
| SEC-11 | No server-side token blacklist la logout | `api/src/middleware/auth.py` |
| SEC-12 | Participant poate face upload (`get_current_user` în loc de `operator+`) | `api/src/routers/inbox.py:49` |
| SEC-13 | DB connection string posibil în startup logs | `stt-worker/src/uploader.py:54` |
| SEC-14 | No max_length pe query string (DoS via 1MB query) | `api/src/routers/search.py:47` |
| SEC-15 | No CSRF protection pe endpoints state-changing | `api/src/main.py` |
| SEC-16 | No dependency locking / vulnerability scanning | `Dockerfile`-uri |

---

## 2. ARHITECTURĂ

### HIGH

**ARCH-1: Race condition la sesiuni multi-segment**
- **Fișier:** `services/stt-worker/src/consumer.py:232-239` + `uploader.py:75-139`
- Dacă 2 workeri procesează simultan segmente din aceeași sesiune, `get_transcript_index_offset()` returnează 0 în ambele → conflict UNIQUE constraint
- **Fix:** `SELECT ... FOR UPDATE` în uploader pentru sesiuni concurente

**ARCH-2: Distributed transaction gap în Ingest**
- **Fișier:** `services/ingest/src/processor.py:131-163`
- Dacă `publish_job()` la Redis eșuează DUPĂ ce recording e creat în DB → recording rămâne `queued` pentru totdeauna fără job activ
- Are try/except dar nu retry → silent failure
- **Fix:** Retry exponențial la publish sau Dead Letter Queue

### MEDIUM

**ARCH-3: Single Point of Failure — PostgreSQL NOTIFY**
- **Fișier:** `services/search-indexer/src/listener.py`
- Dacă conexiunea LISTEN cade, transcriptele noi nu mai sunt indexate semantic până la restart
- **Fix:** Reconnect loop cu bulk reindex periodic

**ARCH-4: Search-indexer bulk reindex blochează HTTP server la startup**
- **Fișier:** `services/search-indexer/src/main.py:74`
- HTTP server pornește DUPĂ reindex → dacă sunt 10k segmente, endpoint-ul `/embed` e down minute
- **Fix:** Pornește HTTP server imediat, reindex în background task

**ARCH-5: Timeout insuficient la search-indexer**
- **Fișier:** `services/api/src/services/search_service.py:309`
- Semantic search poate depăși 5s sub load → întregul request cade fără circuit breaker
- **Fix:** Timeout 15-30s + circuit breaker cu graceful degradation la FTS-only

**ARCH-6: STT-Worker single instance bottleneck**
- Docker Compose definește o singură instanță; 100 joburi procesate serial
- **Fix:** Permite scale-out cu `docker compose up --scale stt-worker=N`

### LOW

**ARCH-7: Connection pool insuficient sub load**
- **Fișier:** `services/api/src/database.py:27-32`
- `pool_size=10, max_overflow=20` → maxim 30 conexiuni simultane; PostgreSQL poate refuza noile cereri
- **Fix:** `pool_size=20, max_overflow=30` pentru producție

---

## 3. CLEAN CODE

### MEDIUM

**CLEAN-1: `FileProcessor.process()` — 120 linii, 6 responsabilități**
- **Fișier:** `services/ingest/src/processor.py:52-173`
- Citire sidecar → validare → dedup → stocare → create recording → publish job, toate inline
- Imposibil de testat fiecare pas izolat
- **Fix:** Desparte în `_validate_and_prepare()`, `_store_and_register()`, `_publish_job()`

**CLEAN-2: `Consumer._process_job()` — 120 linii**
- **Fișier:** `services/stt-worker/src/consumer.py:145-265`
- 8 pași orchestrați într-o funcție → imposibil de testat izolat
- **Fix:** Helper methods per fază

**CLEAN-3: Job eșuat se pierde din Redis**
- **Fișier:** `services/stt-worker/src/consumer.py:261-264`
```python
except Exception as e:
    await self._uploader.mark_failed(...)
    # Job-ul NU e re-queued! User trebuie să reincarce manual
```
- **Fix:** Retry cu exponential backoff (max 3 încercări)

**CLEAN-4: Magic strings pentru rute exempt**
- **Fișier:** `services/api/src/main.py:74-80`
```python
exempt_paths = {"/api/v1/auth/login", "/api/v1/auth/logout", ...}
```
- Dacă redenumești un endpoint, trebuie update în 2 locuri
- **Fix:** Constants module centralizat

**CLEAN-5: Duplicate SQL pentru participant filter**
- **Fișier:** `services/api/src/services/search_service.py:26-47` și `181-200`
- Aceeași condiție WHERE apare în `search()` și `semantic_search()`
- **Fix:** Helper method `_apply_participant_filter(query, user)`

**CLEAN-6: `DatabaseUploader` are prea multe responsabilități**
- **Fișier:** `services/stt-worker/src/uploader.py`
- Connection pool + transcript queries + offset calc + status updates + completeness check
- **Fix:** Desparte în `TranscriptRepository` + `SessionCoordinator`

### LOW

| ID | Descriere | Fișier |
|---|---|---|
| CLEAN-7 | Naming inconsistent (UUID ca str vs uuid.UUID) | `stt-worker/uploader.py:63` |
| CLEAN-8 | Method names ambigue (`search()` vs `search_fts()`) | `search_service.py:55` |
| CLEAN-9 | Middleware `check_must_change_password` mixing concerns | `api/main.py:65-103` |
| CLEAN-10 | Missing docstrings pe métode complexe | `recording_service.py` |
| CLEAN-11 | Error messages fără context (fără ID în 404) | `routers/recordings.py:115` |
| CLEAN-12 | PEP 8 spacing issues | `ingest/processor.py`, `ingest/database.py` |

---

## PRIORITĂȚI DE REMEDIERE

### Imediat (1-2 zile)
1. **SEC-3** — Sanitizare filename la upload (5 minute)
2. **SEC-4** — Stop logging queries sensibile
3. **SEC-7** — HTTPS redirect în nginx
4. **SEC-8** — Security headers în nginx (X-Frame-Options, CSP, HSTS)

### Săptămâna aceasta
5. **SEC-1** — Mută JWT token din query param (breaking change, necesită update frontend)
6. **SEC-2** — Parametrizează vector SQL
7. **SEC-12** — RBAC corect pe inbox upload (participant nu poate upload)
8. **ARCH-1** — `FOR UPDATE` lock pentru sesiuni multi-segment

### Termen mediu (1-2 săptămâni)
9. **ARCH-2** — Retry/DLQ pentru publisher Redis
10. **ARCH-3** — Reconnect loop pentru NOTIFY listener
11. **CLEAN-1/2** — Refactor funcțiile de 120 linii
12. **SEC-11** — Token blacklist Redis la logout

### Termen lung (1-2 luni)
13. **ARCH-6** — Scale-out STT-Worker documentat
14. **SEC-15** — CSRF protection
15. **SEC-16** — Dependency locking + `pip audit` în CI
16. 80% test coverage pe servicii critice

---

## NOTE

Față de analiza anterioară (Rev. 3 din 21 Martie 2026), au fost identificate **23 issues noi** care nu fuseseră detectate anterior, în special:
- **SEC-1** (JWT în URL) — vulnerabilitate prezentă de la implementarea audio streaming
- **SEC-2** (SQL injection vector) — interpolarea string-ului de embedding
- **ARCH-1** (race condition multi-segment) — scenariul cu 2 workeri concurenți
