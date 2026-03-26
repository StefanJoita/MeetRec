# MeetRec Installation Guide

A self-hosted automatic meeting transcription platform. All audio processing runs locally — data never leaves your organization's infrastructure.

---

## Table of Contents

1. [System Requirements](#1-system-requirements)
2. [Automatic Installation (recommended)](#2-automatic-installation-recommended)
3. [Manual Step-by-Step Installation](#3-manual-step-by-step-installation)
4. [SSL Configuration](#4-ssl-configuration)
5. [First Login and Initial Setup](#5-first-login-and-initial-setup)
6. [Advanced Configuration](#6-advanced-configuration)
7. [Updating](#7-updating)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. System Requirements

### Minimum Hardware

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 4 cores | 8+ cores |
| RAM | 8 GB | 16+ GB |
| Storage | 50 GB SSD | 200+ GB SSD |
| GPU | — | NVIDIA (4 GB+ VRAM) |

> **Whisper note:** The `medium` model (default) processes ~1h of audio in 30–60 min on CPU or 3–5 min on an NVIDIA GPU. If transcription speed matters, consider a GPU or the `small` model.

### Required Software

| Software | Minimum Version | Notes |
|----------|----------------|-------|
| **Linux** | Ubuntu 20.04 / Debian 11 | Ubuntu 22.04 LTS recommended |
| **Docker Engine** | 24.0+ | Installed automatically by `install.sh` |
| **Docker Compose** | 2.20+ (plugin v2) | Installed automatically by `install.sh` |
| **curl** | any | Pre-installed on most distributions |
| **openssl** | any | Required for certificate generation |

> **Windows:** Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and [Git for Windows](https://git-scm.com), then run `.\install\install.ps1` — see [Section 2](#2-automatic-installation-recommended).
> **macOS:** Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and follow the [Manual Installation](#3-manual-step-by-step-installation) steps.

### Required Ports

| Port | Protocol | Purpose |
|------|----------|---------|
| 80 | TCP | HTTP → redirect to HTTPS |
| 443 | TCP | HTTPS (web interface) |
| 8080 | TCP | Direct API access (optional, debug only) |

Make sure these ports are open in your server's firewall.

---

## 2. Automatic Installation (recommended)

### Windows (PowerShell)

Requirements: Windows 10/11, [Docker Desktop](https://www.docker.com/products/docker-desktop/), [Git for Windows](https://git-scm.com) (includes openssl).

```powershell
git clone https://github.com/StefanJoita/MeetRec.git
cd MeetRec
.\install\install.ps1
```

The installer accepts optional parameters to skip prompts:

```powershell
.\install\install.ps1 -NonInteractive
.\install\install.ps1 -Domain meetrec.local -WhisperModel small -AdminUser admin -AdminEmail admin@company.com -AdminPassword "S3cur3Pass!"
```

The script will:
1. Verify Docker Desktop is installed and running
2. Ask for domain, Whisper model, and admin credentials
3. Generate `.env` with secure random JWT key and DB password
4. Create data directories (`data/inbox`, `data/processed`, `data/exports`)
5. Generate self-signed SSL certificates
6. Build Docker images (~20–40 min on first run)
7. Start all services and wait for health checks
8. Create the administrator account

> If PowerShell blocks the script, run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

---

### Linux (Ubuntu/Debian)

Works on **Ubuntu 20.04/22.04/24.04** and **Debian 11/12**.

### Step 1 — Clone the repository

```bash
git clone https://github.com/StefanJoita/MeetRec.git
cd MeetRec
```

### Step 2 — Run the installer

```bash
bash install/install.sh
```

The installer will:
1. Check and install Docker if missing
2. Ask for basic configuration (domain, Whisper model)
3. Auto-generate secure passwords and the JWT key
4. Generate SSL certificates (self-signed or Let's Encrypt)
5. Build Docker images (~20–40 min on first run)
6. Start all services
7. Create the administrator account

### Non-interactive option

For CI/CD or to use all defaults:

```bash
bash install/install.sh --non-interactive
```

---

## 3. Manual Step-by-Step Installation

Follow these steps if the automatic installer doesn't work or if you're on macOS or another unsupported platform.

### Step 1 — Install Docker

**Ubuntu / Debian:**
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker   # or log out and back in
```

**Windows / macOS:**
Download and install [Docker Desktop](https://www.docker.com/products/docker-desktop/).

Verify the installation:
```bash
docker --version          # Docker version 24.x.x
docker compose version    # Docker Compose version v2.x.x
```

### Step 2 — Clone the repository

```bash
git clone https://github.com/StefanJoita/MeetRec.git
cd MeetRec
```

### Step 3 — Configure the `.env` file

```bash
cp .env.example .env
```

Open `.env` in an editor and set the **required** values:

```bash
# 1. Generate a unique JWT secret key
python3 -c "import secrets; print(secrets.token_hex(32))"
# → copy the output into JWT_SECRET_KEY

# 2. Choose a database password
# → update POSTGRES_PASSWORD and DATABASE_URL accordingly

# 3. Set your server domain or IP
SERVER_NAME=192.168.1.100     # or meetrec.company.com
```

**Key `.env` parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `JWT_SECRET_KEY` | *(generate)* | JWT secret key — minimum 32 characters |
| `POSTGRES_PASSWORD` | `change_me_in_production` | Database password |
| `SERVER_NAME` | `meeting-transcriber.local` | Server domain or IP |
| `WHISPER_MODEL` | `medium` | Transcription model: `tiny`/`base`/`small`/`medium`/`large` |
| `APP_ENV` | `development` | `production` disables the `/docs` OpenAPI UI |
| `WHISPER_PRIMARY_LANGUAGE` | `ro` | Primary language for transcriptions |
| `RETENTION_DAYS` | `1095` | Days before recordings are auto-deleted (3 years) |

> ⚠️ **Never** commit your `.env` file to Git. It contains secrets!

### Step 4 — Create data directories

```bash
mkdir -p data/inbox data/processed data/exports
```

### Step 5 — Configure SSL certificates

**Option A — Self-signed (LAN/intranet):**

```bash
# localhost or IP
bash install/scripts/gen-self-signed.sh localhost
bash install/scripts/gen-self-signed.sh 192.168.1.100

# or with a domain
bash install/scripts/gen-self-signed.sh meetrec.company.com
```

> Your browser will show a security warning. Click **Advanced → Proceed**. The warning can be removed by adding the certificate to your system's trusted store.

**Option B — Let's Encrypt (public server with a real domain):**

Requirement: the server must be publicly reachable on port 80.

```bash
bash install/scripts/gen-letsencrypt.sh meetrec.company.com admin@company.com
```

Let's Encrypt certificates are valid for 90 days. For automatic renewal, add to crontab:
```bash
0 3 1 * * bash /path/to/MeetRec/install/scripts/gen-letsencrypt.sh meetrec.company.com admin@company.com && docker compose restart nginx
```

### Step 6 — Build Docker images

```bash
docker compose build
```

> ⏱️ The first build takes **20–40 minutes** — the STT worker image includes PyTorch (~3–5 GB to download). Subsequent builds are much faster.

### Step 7 — Start services

```bash
docker compose up -d
```

Verify all services are running:
```bash
docker compose ps
```

All services should have a status of `running` or `healthy`:

```
NAME                STATUS
mt-postgres         running (healthy)
mt-redis            running (healthy)
mt-api              running (healthy)
mt-nginx            running
mt-frontend         running
mt-stt-worker       running (healthy)
mt-ingest           running
mt-audit            running
mt-search-indexer   running
```

### Step 8 — Create the first administrator

```bash
make create-admin
```

Or manually:
```bash
docker compose exec api python3 -c "
import asyncio, uuid, sys
sys.path.insert(0, '/app')
from src.database import AsyncSessionLocal
from src.models.audit_log import User
from passlib.context import CryptContext
from sqlalchemy import select

async def run():
    async with AsyncSessionLocal() as db:
        pwd = CryptContext(schemes=['bcrypt']).hash('YOUR_PASSWORD')
        db.add(User(
            id=uuid.uuid4(),
            username='admin',
            email='admin@company.com',
            hashed_password=pwd,
            role='admin',
            is_active=True,
            force_password_change=True,
        ))
        await db.commit()
        print('Administrator created.')

asyncio.run(run())
"
```

---

## 4. SSL Configuration

### Self-signed for multiple hostnames / IPs

```bash
# Specific IP
bash install/scripts/gen-self-signed.sh 192.168.1.100

# Internal domain
bash install/scripts/gen-self-signed.sh meetrec.local

# Apply the new certificates
docker compose restart nginx
```

### Adding the certificate to the trusted store (removes browser warning)

**Windows:**
1. Open `nginx/ssl/fullchain.pem` → double-click
2. **Install Certificate** → **Local Machine** → **Trusted Root Certification Authorities**

**Ubuntu/Debian:**
```bash
sudo cp nginx/ssl/fullchain.pem /usr/local/share/ca-certificates/meetrec.crt
sudo update-ca-certificates
```

**macOS:**
```bash
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain nginx/ssl/fullchain.pem
```

---

## 5. First Login and Initial Setup

### Access the application

Open in your browser: **`https://YOUR_SERVER`**

> If you're using self-signed certificates, your browser will show a warning. Click **Advanced → Proceed to localhost (unsafe)**.

### Authentication

1. Log in with the administrator credentials created in step 8
2. On first login, the system requires a **password change**
3. Choose a strong new password (minimum 8 characters)

### Adding users

From the **Admin → Users** panel:

| Role | Permissions |
|------|-------------|
| `admin` | Full access, user management, delete recordings |
| `operator` | Upload recordings, manage participants, export |
| `participant` | View transcripts they have been explicitly granted access to |

### First audio file

1. Via the file inbox: copy an audio file to `data/inbox/`
2. Or via the web interface: **Recordings → Add**
3. The system automatically detects the file and begins transcription
4. Status updates in real time: `queued` → `transcribing` → `completed`

### Waiting on first STT Worker start

On first start, Whisper downloads the transcription model:

| Model | Size | Download time (100 Mbps) |
|-------|------|--------------------------|
| `tiny` | ~75 MB | ~6 sec |
| `base` | ~140 MB | ~11 sec |
| `small` | ~460 MB | ~37 sec |
| `medium` | ~1.5 GB | ~2 min |
| `large` | ~3 GB | ~4 min |

Monitor progress with:
```bash
docker compose logs -f stt-worker
```

The model is downloaded once and stored in the `whisper_models` Docker volume.

---

## 6. Advanced Configuration

### NVIDIA GPU (much faster transcription)

1. Install the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html):
```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

2. Uncomment the GPU block in `docker-compose.yml`:
```yaml
stt-worker:
  # ...
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
```

3. Rebuild and restart:
```bash
docker compose build stt-worker
docker compose up -d stt-worker
```

### Changing the HTTPS port

In `.env`:
```bash
NGINX_HTTPS_PORT=8443
```

Then:
```bash
docker compose up -d nginx
```

The application will be accessible at `https://server:8443`.

### Semantic search (AI)

On first start, `search-indexer` downloads the embeddings model (~120 MB). Once it has started successfully, set in `.env`:

```bash
HF_HUB_OFFLINE=1
```

This prevents online checks on every restart.

### Data backup

Important data is stored in Docker volumes:

```bash
# Database backup
docker compose exec postgres pg_dump -U mt_user meeting_transcriber > backup_$(date +%Y%m%d).sql

# Audio files backup (Docker volume → local directory)
docker run --rm -v meetrec_audio_storage:/data -v $(pwd):/backup \
    alpine tar czf /backup/audio_backup_$(date +%Y%m%d).tar.gz /data
```

---

## 7. Updating

```bash
# 1. Pull the latest version
git pull

# 2. Rebuild images
docker compose build

# 3. Restart with automatic database migrations
docker compose up -d
```

Alembic migrations run automatically at API container startup.

---

## 8. Troubleshooting

### Services won't start

```bash
# Check status and logs
docker compose ps
docker compose logs --tail=50 api
docker compose logs --tail=50 postgres
```

### Error: `DATABASE_URL must use postgresql+asyncpg://`

Check that the database URL in `.env` uses the correct protocol:
```bash
DATABASE_URL=postgresql+asyncpg://mt_user:PASSWORD@postgres:5432/meeting_transcriber
#                        ^^^^^^^^ required
```

### Transcription stuck in `queued`

The STT worker may still be initializing (downloading the Whisper model). Monitor with:
```bash
docker compose logs -f stt-worker
# Wait for: "Whisper model loaded, waiting for jobs..."
```

### Browser shows "Connection refused" on port 443

Check that nginx is running and port 443 is free on the server:
```bash
docker compose ps nginx
sudo lsof -i :443   # check if another process is using the port
```

### SSL error: `certificate verify failed`

If you're using self-signed certificates and a non-browser client returns this error:
```bash
# Check that certificates exist
ls -la nginx/ssl/

# Regenerate if missing
bash install/scripts/gen-self-signed.sh localhost
docker compose restart nginx
```

### Cannot access the API from the browser (CORS)

Make sure `APP_ENV` is set correctly in `.env`:
- `development` — permissive CORS, `/docs` accessible
- `production` — CORS restricted to the configured domain

### Real-time logs

```bash
make logs              # all services
make logs-api          # API only
make logs-stt-worker   # transcription worker only
make logs-nginx        # nginx access and errors
```

### Full reset (deletes all data!)

```bash
make clean-all   # stop containers and delete data volumes
make setup       # reconfigure
make build
make start
```

---

## Quick Command Reference

```bash
make start           # start all services
make stop            # stop all services
make restart         # restart services
make ps              # service status
make logs            # real-time logs
make build           # rebuild Docker images
make ssl-self-signed # regenerate self-signed SSL certificates
make create-admin    # create an administrator user
make db-shell        # PostgreSQL shell
make redis-cli       # Redis shell
make api-shell       # shell into the API container
make test            # run backend tests
```
