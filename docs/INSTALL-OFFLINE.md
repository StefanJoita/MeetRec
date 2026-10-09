# MeetRec — Manual de instalare offline (air-gapped)

Acest manual descrie instalarea MeetRec pe un server **fără acces la internet**.
Procesul are două părți:

| Parte | Unde | Ce se întâmplă |
|-------|------|----------------|
| **A. Pregătire pachet** | Mașină cu internet + Docker | Se descarcă modelele ML, se construiesc imaginile, se descarcă Docker Engine și se creează o arhivă unică |
| **B. Instalare** | Serverul offline | Se instalează Docker din pachet, se încarcă imaginile, se generează configurația și certificatele, se pornesc serviciile |

După instalare, **nicio componentă nu mai face cereri în afara serverului**: modelele sunt incluse în imagini, fonturile sunt incluse în frontend, iar `HF_HUB_OFFLINE=1` e setat în imagini.

---

## Cuprins

1. [Cerințe](#1-cerințe)
2. [Inventarul complet al dependențelor](#2-inventarul-complet-al-dependențelor)
3. [Partea A — Pregătirea pachetului (mașina cu internet)](#3-partea-a--pregătirea-pachetului-mașina-cu-internet)
4. [Transferul pe serverul offline](#4-transferul-pe-serverul-offline)
5. [Partea B — Instalarea pe serverul offline](#5-partea-b--instalarea-pe-serverul-offline)
6. [Certificate HTTPS și configurarea clienților](#6-certificate-https-și-configurarea-clienților)
7. [Verificare după instalare](#7-verificare-după-instalare)
8. [Configurare](#8-configurare)
9. [Operare: pornire, loguri, backup, restaurare](#9-operare-pornire-loguri-backup-restaurare)
10. [Actualizare la o versiune nouă](#10-actualizare-la-o-versiune-nouă)
11. [Depanare](#11-depanare)
12. [Securitate](#12-securitate)
13. [Anexă — instalare manuală, pas cu pas, fără script](#13-anexă--instalare-manuală-pas-cu-pas-fără-script)

---

## 1. Cerințe

### 1.1 Serverul offline (țintă)

| Resursă | Minim | Recomandat | Observații |
|---------|-------|------------|------------|
| Arhitectură | x86_64 (amd64) | — | ARM nu e suportat de pachet |
| Sistem de operare | Ubuntu 22.04 / 24.04, Debian 12 | Ubuntu 24.04 LTS | Alte distribuții: Docker din binare statice (§11.2) |
| CPU | 4 nuclee | 8+ nuclee | Transcrierea rulează pe CPU |
| RAM | 16 GB | 32 GB | Whisper large-v3 + aliniere + diarizare ≈ 8–10 GB |
| Disc | 60 GB liberi | 200 GB+ | ~25 GB imagini (dezarhivate) + pachet + înregistrări audio |
| Rețea | — | IP fix / nume DNS intern | Utilizatorii accesează `https://<server>` |
| Acces | root / sudo | — | — |

**Pachete de sistem necesare pe server** (instalate implicit pe Ubuntu Server și Debian standard):

| Pachet | Folosit de |
|--------|------------|
| `iptables`, `nftables` | Docker Engine (rețelistica containerelor) |
| `libseccomp2`, `libsystemd0`, `libc6` (≥ 2.34) | containerd / Docker |
| `systemd` | pornirea automată a Docker |
| `openssl` | generarea certificatelor HTTPS |
| `coreutils` (`sha256sum`, `od`), `gzip`, `tar` | installer |

Installerul le verifică pe cele critice și se oprește cu un mesaj clar dacă lipsesc (vezi §11.1).

**Durata transcrierii pe CPU**: cu `large-v3`, 1 oră de audio durează aproximativ 1–2 ore pe un server cu 8 nuclee. Joburile sunt procesate pe rând, în ordinea sosirii.

### 1.2 Mașina de pregătire (cu internet)

| Cerință | Detalii |
|---------|---------|
| Docker | Docker Engine 24+ cu Compose v2 (Linux) **sau** Docker Desktop (Windows/macOS) |
| Shell | `bash` (pe Windows: Git Bash) |
| Unelte | `curl`, `gzip`, `tar`, `sha256sum` (incluse în Git Bash) |
| Disc | ~60 GB liberi (modele + cache build + pachet) |
| Internet | acces la `huggingface.co`, `pypi.org`, `download.pytorch.org`, `registry.npmjs.org`, `registry-1.docker.io`, `download.docker.com`, `github.com`, `deb.debian.org` |
| Arhitectură | x86_64 (imaginile se construiesc pentru `linux/amd64`) |

---

## 2. Inventarul complet al dependențelor

Tot ce e listat aici este inclus în pachet. Versiunile exacte ale pachetului generat (ID-urile imaginilor, reviziile modelelor) sunt scrise automat în `MANIFEST.txt`.

### 2.1 Imagini Docker

| Imagine | Sursă | Conține |
|---------|-------|---------|
| `meetrec/api:<versiune>` | construită local | FastAPI, Python 3.11, migrații Alembic, CLI `create_admin`, fonturi DejaVu (export PDF) |
| `meetrec/ingest:<versiune>` | construită local | watcher inbox, validare audio, ffmpeg |
| `meetrec/stt-worker:<versiune>` | construită local | WhisperX 3.8.6, PyTorch 2.8.0 (CPU), ffmpeg, **toate modelele de transcriere** |
| `meetrec/search-indexer:<versiune>` | construită local | sentence-transformers 3.0.1, PyTorch 2.4.0 (CPU), **modelul de embeddings** |
| `meetrec/audit-retention:<versiune>` | construită local | retenție date și audit |
| `meetrec/frontend:<versiune>` | construită local | aplicația React compilată + nginx, **font Inter inclus** |
| `pgvector/pgvector:pg15` | Docker Hub | PostgreSQL 15 + extensiile pgvector, unaccent, uuid-ossp |
| `redis:7-alpine` | Docker Hub | coada de joburi |
| `nginx:1.25-alpine` | Docker Hub | reverse proxy + HTTPS |

### 2.2 Modele ML (incluse în imagini)

| Model | Folosit pentru | Dimensiune | Licență | Locație în imagine |
|-------|----------------|-----------:|---------|--------------------|
| `Systran/faster-whisper-large-v3` | transcriere | ~2.9 GB | MIT | `stt-worker:/app/models/whisper` |
| `gigant/romanian-wav2vec2` | aliniere la nivel de cuvânt (română) | ~1.2 GB | Apache-2.0 | `stt-worker:/app/models/huggingface/hub` |
| `pyannote/speaker-diarization-community-1` | diarizare (identificare vorbitori) — **opțional** | ~30 MB | CC-BY-4.0 (acces cu acceptarea termenilor) | `stt-worker:/app/models/huggingface/hub` |
| Model VAD pyannote (inclus în pachetul `whisperx`) | detecția vorbirii | ~17 MB | inclus în whisperx | `site-packages/whisperx/assets` |
| NLTK `punkt_tab` | segmentare în propoziții la aliniere | ~15 MB | vezi <https://www.nltk.org/nltk_data/> | `stt-worker:/app/models/nltk_data` |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | căutare semantică | ~470 MB | Apache-2.0 | `search-indexer:/app/models` |

### 2.3 Docker Engine pentru server (în `packages/docker/`)

| Fișier | Pentru |
|--------|--------|
| `deb/jammy/*.deb` | Ubuntu 22.04 |
| `deb/noble/*.deb` | Ubuntu 24.04 |
| `deb/bookworm/*.deb` | Debian 12 |
| `static/docker-<ver>.tgz` + `static/docker-compose-linux-x86_64` | orice altă distribuție x86_64 cu systemd |

Fiecare set `.deb` conține: `containerd.io`, `docker-ce-cli`, `docker-ce`, `docker-buildx-plugin`, `docker-compose-plugin` (ultimele versiuni stabile de la data generării pachetului, de pe `download.docker.com`).

### 2.4 Alte dependențe incluse

| Componentă | Unde |
|------------|------|
| Font Inter 400/500/600/700 (latin + latin-ext, cu diacritice) | bundle frontend (`@fontsource/inter`), licență OFL-1.1 |
| Fonturi DejaVu (export PDF cu diacritice) | imaginea `api` (`fonts-dejavu-core`) |
| ffmpeg | imaginile `ingest` și `stt-worker` |
| Scripturi certificate (`gen-local-ca.sh`, `gen-self-signed.sh`) | `install/certs/` |

### 2.5 Ce NU este inclus

- **Sistemul de operare** și pachetele lui de bază (§1.1).
- **Driver/CUDA NVIDIA**: pachetul e exclusiv CPU.
- **Certificatul organizației**: dacă folosiți CA-ul intern al organizației, certificatul se obține separat (§6.3).

---

## 3. Partea A — Pregătirea pachetului (mașina cu internet)

### 3.1 Clonează proiectul și creează `.env`

```bash
git clone <url-repo> MeetRec
cd MeetRec
cp .env.example .env
```

În `.env`, pe mașina de pregătire contează doar:

| Variabilă | Valoare | Rol |
|-----------|---------|-----|
| `MEETREC_VERSION` | ex. `1.0.0` | tag-ul imaginilor și numele pachetului |
| `WHISPER_MODEL` | `large-v3` (implicit) | modelul inclus în imagine. Alternative: `medium`, `small` |
| `HF_TOKEN` | token HuggingFace | **doar** pentru diarizare (§3.2). Gol = fără diarizare |

Celelalte valori (parole etc.) se generează pe serverul offline. Nu copia acest `.env` pe server.

### 3.2 (Opțional) Diarizare — token HuggingFace

Modelul `pyannote/speaker-diarization-community-1` se descarcă doar după acceptarea termenilor:

1. Creează un cont pe <https://huggingface.co>.
2. Deschide <https://huggingface.co/pyannote/speaker-diarization-community-1> și acceptă condițiile de acces.
3. Creează un token de tip **Read** la <https://huggingface.co/settings/tokens>.
4. Pune-l în `.env`: `HF_TOKEN=hf_...`

Tokenul e folosit **doar** la descărcarea modelului. Nu ajunge în imagini și nu e necesar pe server.

### 3.3 Construiește pachetul

```bash
bash install/offline/build-bundle.sh
```

Pe Windows: rulează comanda din **Git Bash**, cu Docker Desktop pornit.

Scriptul face, în ordine:

1. verifică Docker și uneltele necesare;
2. descarcă modelele ML în `services/*/models/`, dacă lipsesc (`install/models/download-models.py`, rulat într-un container `python:3.11-slim`);
3. construiește cele 6 imagini `meetrec/*` pentru `linux/amd64` și descarcă imaginile de bază;
4. exportă toate imaginile cu `docker save` în `images/*.tar.gz`;
5. descarcă Docker Engine (`.deb` + binare statice) — sari peste pas cu `SKIP_DOCKER_PACKAGES=1` dacă serverul are deja Docker;
6. copiază fișierele de deployment și generează un `docker-compose.yml` fără `build:` și cu `pull_policy: never`;
7. calculează `SHA256SUMS`, scrie `MANIFEST.txt` și creează arhiva.

Durata: 30–60 de minute la prima rulare (descărcarea PyTorch și a modelelor).

**Rezultat:**

```
dist/meetrec-offline-<versiune>.tar          (~8–10 GB)
dist/meetrec-offline-<versiune>.tar.sha256
```

Modelele se pot descărca și separat, fără să construiești pachetul:

```bash
python install/models/download-models.py                     # necesită: pip install "huggingface_hub>=0.26,<1.0" nltk
# sau, doar cu Docker:
bash install/models/download-models-docker.sh
```

Opțiuni: `--whisper-model medium`, `--skip-diarization`.

### 3.4 Structura pachetului

```
meetrec-offline-<versiune>/
├── install-offline.sh          ← installerul pentru server
├── docker-compose.yml          ← varianta offline (fără build:, pull_policy: never)
├── .env.example
├── MANIFEST.txt                ← versiuni imagini, revizii modele, pachete Docker
├── SHA256SUMS                  ← sume de control pentru toate fișierele
├── database/init.sql           ← schema inițială a bazei de date
├── nginx/                      ← configurația reverse proxy (+ ssl/ pentru certificate)
├── install/certs/              ← gen-local-ca.sh, gen-self-signed.sh
├── images/                     ← 9 imagini Docker (.tar.gz)
├── packages/docker/            ← Docker Engine + Compose pentru server
├── data/                       ← inbox / processed / exports
└── docs/INSTALL-OFFLINE.md     ← acest manual
```

---

## 4. Transferul pe serverul offline

1. Copiază `meetrec-offline-<versiune>.tar` și `.tar.sha256` pe un mediu de transfer: disc USB formatat **ext4 sau exFAT** (FAT32 nu acceptă fișiere > 4 GB), sau un share de rețea aprobat.
2. Pe server, verifică arhiva înainte de dezarhivare:

```bash
sha256sum -c meetrec-offline-<versiune>.tar.sha256
# meetrec-offline-<versiune>.tar: OK
```

3. Dezarhivează într-o locație permanentă. Recomandat: `/opt`.

```bash
sudo tar -xf meetrec-offline-<versiune>.tar -C /opt
sudo ln -sfn /opt/meetrec-offline-<versiune> /opt/meetrec
cd /opt/meetrec
```

Directorul de instalare conține `.env` (secrete), certificatele și `data/inbox`. Nu-l șterge după instalare.

---

## 5. Partea B — Instalarea pe serverul offline

```bash
cd /opt/meetrec
sudo ./install-offline.sh
```

Pentru instalare fără întrebări (valori implicite: IP-ul serverului, CA locală, diarizare activă dacă e inclusă), rulează `sudo ./install-offline.sh --non-interactive`. Administratorul se configurează apoi manual (§5.8).

### 5.1 Pasul 1 — Verificare sistem și pachet

Installerul verifică:
- rularea ca root și arhitectura x86_64;
- RAM-ul (avertisment sub 16 GB) și spațiul pe disc (avertisment sub 40 GB);
- integritatea tuturor fișierelor, față de `SHA256SUMS`.

### 5.2 Pasul 2 — Docker Engine

- Dacă Docker și Compose v2 există deja, pasul e sărit.
- Altfel, citește `VERSION_CODENAME` din `/etc/os-release`:
  - `jammy` / `noble` / `bookworm`: instalează `.deb`-urile din `packages/docker/deb/<codename>/`, după ce verifică `iptables`, `nftables`, `libseccomp2` și `libsystemd0`;
  - altă distribuție: instalează binarele statice în `/usr/bin` și unitățile systemd `containerd.service` și `docker.service`.
- Pornește și activează serviciile la boot (`systemctl enable --now containerd docker`).

### 5.3 Pasul 3 — Încărcarea imaginilor

`gunzip -c images/X.tar.gz | docker load` pentru fiecare dintre cele 9 imagini (5–15 minute).

### 5.4 Pasul 4 — Configurația `.env`

Dacă `.env` nu există, e creat din `.env.example` cu:

| Variabilă | Valoare |
|-----------|---------|
| `POSTGRES_PASSWORD` + `DATABASE_URL` | parolă aleatoare (32 hex) |
| `REDIS_PASSWORD` | parolă aleatoare (48 hex) |
| `JWT_SECRET_KEY` | cheie aleatoare (64 hex) |
| `SERVER_NAME` | întrebat; implicit primul IP al serverului |
| `WHISPER_MODEL` | din `MANIFEST.txt` (modelul inclus în imagine) |
| `DIARIZATION_ENABLED` | întrebat, dacă modelul pyannote e inclus; altfel `false` |
| `APP_ENV` | `production` |
| `MEETREC_VERSION` | versiunea pachetului |

`.env` primește permisiuni `600`. La o re-rulare, fișierul existent e păstrat neschimbat.

### 5.5 Pasul 5 — Certificate HTTPS

Dacă nu există `nginx/ssl/fullchain.pem` și `privkey.pem`, poți alege:
1. **CA locală MeetRec** (recomandat) — §6.1
2. **Self-signed** — §6.2
3. **Certificatul organizației** — scriptul se oprește; copiezi certificatul și rulezi din nou (§6.3)

### 5.6 Pasul 6 — Pornirea serviciilor

```bash
docker compose up -d --no-build --pull never
```

- `data/inbox` primește proprietarul UID 1000 (utilizatorul din containerul API).
- Installerul așteaptă până la 3 minute ca API-ul să răspundă la `/health`.
- `stt-worker` mai are nevoie de 1–3 minute ca să încarce modelul Whisper.

### 5.7 Pasul 7 — Contul de administrator

Installerul cere username, email și parolă (minim 8 caractere) și rulează în containerul API:

```bash
python -m src.cli.create_admin --username <user> --email <email> --update-existing --disable-default-operator
```

- `--update-existing`: dacă alegi `admin`, suprascrie parola implicită `admin123` din `init.sql`.
- `--disable-default-operator`: dezactivează contul implicit `operator`, dacă încă are parola `operator123`.

### 5.8 Configurarea manuală a administratorului

Folosește-o dacă ai rulat installerul cu `--non-interactive` sau dacă pasul 7 a eșuat:

```bash
cd /opt/meetrec
docker compose exec api python -m src.cli.create_admin \
    --username admin --email admin@firma.ro --update-existing --disable-default-operator
# parola se cere interactiv
```

---

## 6. Certificate HTTPS și configurarea clienților

### 6.1 CA locală MeetRec (recomandat)

```bash
cd /opt/meetrec
sudo bash install/certs/gen-local-ca.sh meetrec.firma.local 192.168.10.5   # toate numele + IP-urile folosite
docker compose restart nginx
```

| Fișier | Rol | Distribuire |
|--------|-----|-------------|
| `nginx/ssl/meetrec-ca.crt` | certificatul CA (public) | **pe toate calculatoarele client** |
| `nginx/ssl/ca/meetrec-ca.key` | cheia CA | **secretă** — backup offline, nu o distribui |
| `nginx/ssl/fullchain.pem`, `privkey.pem` | certificatul serverului (825 zile) | folosite doar de nginx |

Pentru reînnoire, rulează din nou scriptul: CA-ul e refolosit, deci clienții nu trebuie reconfigurați.

**Importul `meetrec-ca.crt` pe clienți:**

| Platformă | Comandă / pași |
|-----------|----------------|
| Windows (un calculator) | `certutil -addstore -f Root meetrec-ca.crt` (Command Prompt ca Administrator) |
| Windows (domeniu) | GPO: *Computer Configuration → Policies → Windows Settings → Security Settings → Public Key Policies → Trusted Root Certification Authorities → Import* |
| macOS | `sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain meetrec-ca.crt` |
| Ubuntu / Debian | `sudo cp meetrec-ca.crt /usr/local/share/ca-certificates/ && sudo update-ca-certificates` |
| Firefox | *Settings → Privacy & Security → Certificates → View Certificates → Authorities → Import* (sau `security.enterprise_roots.enabled = true` pe Windows/macOS) |
| Chrome / Edge | folosesc depozitul sistemului (rândurile de mai sus) |

### 6.2 Self-signed

```bash
sudo bash install/certs/gen-self-signed.sh meetrec.firma.local
docker compose restart nginx
```

Browserul afișează un avertisment pe fiecare client, până la acceptarea manuală a excepției. E potrivit doar pentru teste.

### 6.3 Certificatul organizației

Copiază certificatul (inclusiv lanțul intermediar) și cheia:

```bash
sudo cp server-cu-lant.pem /opt/meetrec/nginx/ssl/fullchain.pem
sudo cp server.key        /opt/meetrec/nginx/ssl/privkey.pem
sudo chmod 600 /opt/meetrec/nginx/ssl/privkey.pem
docker compose restart nginx
```

Certificatul trebuie să conțină în SAN numele și IP-ul folosite de utilizatori.

### 6.4 Numele serverului (DNS)

Rețeaua offline are nevoie de rezolvarea numelui. Ai două variante:
- o înregistrare în DNS-ul intern (`meetrec.firma.local → 192.168.10.5`);
- sau o intrare în `hosts` pe fiecare client (`C:\Windows\System32\drivers\etc\hosts`, `/etc/hosts`).

Accesul direct prin IP funcționează dacă IP-ul se află în certificat (§6.1 îl adaugă automat).

---

## 7. Verificare după instalare

```bash
cd /opt/meetrec

# 1. Toate containerele pornite (api: healthy)
docker compose ps

# 2. API
docker compose exec api curl -s http://localhost:8080/health

# 3. Modelul Whisper încărcat
docker compose logs stt-worker | grep -E "models_loaded|whisper_model_ready|align_model_ready|diarization"

# 4. Embeddings încărcate
docker compose logs search-indexer | grep embedding_model_loaded

# 5. Modul offline e activ în imagini
docker compose exec stt-worker env | grep -E "HF_HUB_OFFLINE|TRANSFORMERS_OFFLINE"   # =1

# 6. HTTPS de pe un client
curl -I https://meetrec.firma.local          # fără -k dacă CA-ul e importat
```

**Test funcțional:**
1. Deschide `https://<server>` și autentifică-te cu administratorul.
2. *Înregistrări → Adaugă*: încarcă un fișier audio scurt (30–60 de secunde, în română).
3. Statusul trebuie să treacă prin `queued`, `transcribing` și `completed`.
4. Deschide transcrierea: textul are timestamps, iar dacă diarizarea e activă, are și vorbitori (`SPEAKER_00`…).
5. *Căutare*: caută un cuvânt din transcriere (full-text și semantic).
6. Exportă transcrierea în PDF și DOCX și verifică diacriticele.

---

## 8. Configurare

Fișierul `/opt/meetrec/.env`. După orice modificare: `docker compose up -d`.

| Variabilă | Implicit | Descriere |
|-----------|----------|-----------|
| `SERVER_NAME` | IP-ul serverului | numele afișat (certificatele se generează separat, §6) |
| `WHISPER_MODEL` | `large-v3` | **trebuie** să fie modelul inclus în imagine; alt model cere un pachet nou |
| `WHISPER_COMPUTE_TYPE` | `int8` | `int8` (rapid, CPU) sau `float32` |
| `DIARIZATION_ENABLED` | `true`/`false` | funcționează doar dacă `MANIFEST.txt` are `Diarizare: da` |
| `MIN_SPEAKERS` / `MAX_SPEAKERS` | gol | indicații pentru diarizare |
| `MAX_FILE_SIZE_BYTES` | `524288000` | dimensiunea maximă a unui fișier audio (500 MB) |
| `RETENTION_DAYS` | `1095` | după câte zile se șterg înregistrările |
| `AUDIT_LOG_RETENTION_DAYS` | `2190` | retenția jurnalului de audit |
| `JWT_EXPIRE_MINUTES` | `480` | durata sesiunii |
| `NGINX_HTTPS_PORT` | `443` | portul HTTPS |
| `LOG_LEVEL` | `INFO` | `DEBUG` pentru depanare |

**Firewall:** expune doar porturile **80** (redirect) și **443**. PostgreSQL, Redis, API-ul și search-indexer nu sunt publicate pe host.

```bash
sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
```

---

## 9. Operare: pornire, loguri, backup, restaurare

Toate comenzile se rulează din `/opt/meetrec`.

| Acțiune | Comandă |
|---------|---------|
| Status | `docker compose ps` |
| Loguri | `docker compose logs -f --tail=100 [serviciu]` |
| Oprire | `docker compose stop` |
| Pornire | `docker compose up -d` |
| Repornire serviciu | `docker compose restart stt-worker` |
| Coada de transcriere | `docker compose exec redis redis-cli LLEN transcription_jobs` |

Serviciile au `restart: unless-stopped` și pornesc automat după un reboot.

### 9.1 Date persistente

| Volum Docker | Conținut |
|--------------|----------|
| `meetrec_postgres_data` | baza de date (utilizatori, transcrieri, audit) |
| `meetrec_audio_storage` | fișierele audio procesate |
| `meetrec_export_storage` | exporturi PDF/DOCX |
| `meetrec_redis_data` | coada de joburi |
| `/opt/meetrec/.env`, `/opt/meetrec/nginx/ssl/` | configurație, secrete, certificate |

### 9.2 Backup

```bash
cd /opt/meetrec
BK=/backup/meetrec-$(date +%F); sudo mkdir -p $BK

# Baza de date (consistent, cu serviciile pornite)
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > $BK/db.dump

# Audio + exporturi
for v in audio_storage export_storage; do
  docker run --rm -v meetrec_$v:/src:ro -v $BK:/dst alpine tar -czf /dst/$v.tar.gz -C /src .
done

# Configurație + certificate (conțin secrete — păstrează backup-ul protejat)
sudo tar -czf $BK/config.tar.gz .env nginx/ssl
```

Imaginea `alpine` e folosită doar pentru backup și nu face parte din pachet. Pe un server offline, ca alternativă, folosește o imagine deja încărcată:

```bash
docker run --rm --entrypoint tar -v meetrec_audio_storage:/src:ro -v $BK:/dst redis:7-alpine -czf /dst/audio_storage.tar.gz -C /src .
```

### 9.3 Restaurare

```bash
cd /opt/meetrec
docker compose stop api ingest stt-worker search-indexer audit-retention
docker compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' < $BK/db.dump
docker run --rm --entrypoint sh -v meetrec_audio_storage:/dst -v $BK:/src:ro redis:7-alpine \
    -c 'rm -rf /dst/* && tar -xzf /src/audio_storage.tar.gz -C /dst'
docker compose up -d
```

---

## 10. Actualizare la o versiune nouă

1. Pe mașina cu internet: `git pull`, apoi `MEETREC_VERSION=<nouă> bash install/offline/build-bundle.sh` (§3.3).
2. Transferă și verifică arhiva (§4).
3. Pe server:

```bash
# backup înainte de actualizare (§9.2)
sudo tar -xf meetrec-offline-<nouă>.tar -C /opt
cd /opt/meetrec-offline-<nouă>

# preia configurația, certificatele și inbox-ul din instalarea curentă
sudo cp -a /opt/meetrec/.env .
sudo cp -a /opt/meetrec/nginx/ssl/. nginx/ssl/
sudo cp -a /opt/meetrec/data/. data/

sudo ./install-offline.sh          # încarcă imaginile noi, păstrează .env, actualizează MEETREC_VERSION
sudo ln -sfn /opt/meetrec-offline-<nouă> /opt/meetrec
```

- Volumele de date se păstrează: proiectul Compose are nume fix (`name: meetrec`), indiferent de director.
- Migrațiile bazei de date (Alembic) rulează automat la pornirea API-ului.
- **Revenire la versiunea anterioară:** `cd /opt/meetrec-offline-<veche>`, setează `MEETREC_VERSION=<veche>` în `.env`, apoi `docker compose up -d`. Imaginile vechi rămân încărcate până la `docker image prune`. Restaurează și backup-ul bazei de date dacă versiunea nouă a aplicat migrații.

---

## 11. Depanare

### 11.1 „Lipsesc pachetele de sistem: …”

Pe o mașină **cu internet**, cu aceeași versiune de sistem ca serverul:

```bash
mkdir deps && cd deps
apt-get download iptables nftables libnftables1 libnftnl11 libjansson4 libxtables12 \
    libip4tc2 libip6tc2 libnetfilter-conntrack3 libnfnetlink0 libmnl0 libseccomp2
```

Copiază `.deb`-urile pe server și rulează `sudo dpkg -i *.deb`, apoi `sudo ./install-offline.sh`.

### 11.2 Distribuție fără `.deb`-uri în pachet

Installerul folosește automat binarele statice (`packages/docker/static/`). Condiții: systemd, `iptables` și kernel ≥ 4.x cu `overlay`. Verificare: `systemctl status docker`.

### 11.3 `stt-worker` repornește continuu

```bash
docker compose logs --tail=200 stt-worker
```

| Mesaj | Cauză | Soluție |
|-------|-------|---------|
| `Killed` / exit code 137 | memorie insuficientă (OOM) | mai mult RAM, `DIARIZATION_ENABLED=false`, sau un pachet nou cu `--whisper-model medium` |
| `LocalEntryNotFoundError` / `couldn't connect to huggingface.co` | `WHISPER_MODEL` diferă de modelul inclus | pune în `.env` valoarea din `MANIFEST.txt` → `Model Whisper` |
| `diarization_model_failed` | pachet fără pyannote | `DIARIZATION_ENABLED=false` |

### 11.4 Upload-ul eșuează cu 500 / „Permission denied”

```bash
sudo chown 1000:1000 /opt/meetrec/data/inbox
```

### 11.5 Browserul afișează „conexiune nesigură”

- `meetrec-ca.crt` nu e importat pe client (§6.1);
- sau numele/IP-ul folosit nu e în certificat. Verifică cu `openssl x509 -in nginx/ssl/fullchain.pem -noout -ext subjectAltName` și regenerează cu toate numele.
- Ceasul clientului sau al serverului e greșit: în rețelele offline, configurează un server NTP intern.

### 11.6 Containerul API nu pornește: „users table missing”

`init.sql` a eșuat la prima pornire a PostgreSQL. **Doar pe o instalare nouă, fără date:**

```bash
docker compose down -v && docker compose up -d
```

### 11.7 Verificare că nu există trafic spre internet

```bash
# niciun container nu trebuie să încerce conexiuni externe
sudo tcpdump -ni any 'not net 10.0.0.0/8 and not net 172.16.0.0/12 and not net 192.168.0.0/16 and not host 127.0.0.1' -c 20
```

---

## 12. Securitate

- **Conturi implicite** (`init.sql`): `admin/admin123` și `operator/operator123`, ambele cu schimbarea parolei obligatorie la primul login. Installerul suprascrie parola `admin` și dezactivează `operator`. Verifică în *Admin → Utilizatori*.
- **`.env`** conține parolele DB/Redis și cheia JWT: permisiuni `600`, inclus în backup-ul protejat.
- **Cheia CA** (`nginx/ssl/ca/meetrec-ca.key`): oricine o deține poate emite certificate acceptate de clienți. Păstreaz-o offline.
- **Porturi:** doar 80/443 sunt publicate. `docker-compose.dev.yml` (porturi de debugging) **nu** face parte din pachet.
- **Redis** necesită parolă, iar PostgreSQL nu e accesibil din afara rețelei Docker.
- **`APP_ENV=production`** dezactivează `/docs` și `/redoc`.

---

## 13. Anexă — instalare manuală, pas cu pas, fără script

Echivalentul `install-offline.sh`, pentru medii în care scripturile trebuie auditate sau rulate pas cu pas:

```bash
cd /opt/meetrec
sha256sum --quiet -c SHA256SUMS

# Docker (Ubuntu 24.04)
sudo dpkg -i packages/docker/deb/noble/{containerd.io,docker-ce-cli,docker-ce,docker-buildx-plugin,docker-compose-plugin}_*.deb
sudo systemctl enable --now containerd docker

# Imagini
for f in images/*.tar.gz; do gunzip -c "$f" | sudo docker load; done

# Configurație
cp .env.example .env && chmod 600 .env
DBP=$(openssl rand -hex 16)
sed -i "s|change_me_in_production|$DBP|g" .env
sed -i "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=$(openssl rand -hex 32)|" .env
sed -i "s|^REDIS_PASSWORD=.*|REDIS_PASSWORD=$(openssl rand -hex 24)|" .env
sed -i "s|^SERVER_NAME=.*|SERVER_NAME=meetrec.firma.local|" .env
sed -i "s|^MEETREC_VERSION=.*|MEETREC_VERSION=$(awk '/^Versiune:/{print $2}' MANIFEST.txt)|" .env
sed -i "s|^WHISPER_MODEL=.*|WHISPER_MODEL=$(awk '/^Model Whisper:/{print $3}' MANIFEST.txt)|" .env
# DIARIZATION_ENABLED=true doar dacă MANIFEST.txt are "Diarizare: da"

# Certificate
sudo bash install/certs/gen-local-ca.sh meetrec.firma.local 192.168.10.5

# Pornire
sudo chown 1000:1000 data/inbox
sudo docker compose up -d --no-build --pull never

# Administrator
sudo docker compose exec api python -m src.cli.create_admin \
    --username admin --email admin@firma.ro --update-existing --disable-default-operator
```
