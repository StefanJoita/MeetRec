# Ghid de instalare MeetRec

Platformă self-hosted de transcriere automată a ședințelor. Tot procesarea audio se face local — datele nu părăsesc infrastructura organizației.

---

## Cuprins

1. [Cerințe sistem](#1-cerințe-sistem)
2. [Instalare automată (recomandată)](#2-instalare-automată-recomandată)
3. [Instalare manuală pas cu pas](#3-instalare-manuală-pas-cu-pas)
4. [Configurare SSL](#4-configurare-ssl)
5. [Primul login și configurare inițială](#5-primul-login-și-configurare-inițială)
6. [Configurare avansată](#6-configurare-avansată)
7. [Actualizare versiune](#7-actualizare-versiune)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. Cerințe sistem

### Hardware minim

| Componentă | Minim | Recomandat |
|------------|-------|------------|
| CPU | 4 nuclee | 8+ nuclee |
| RAM | 8 GB | 16+ GB |
| Stocare | 50 GB SSD | 200+ GB SSD |
| GPU | — | NVIDIA (VRAM 4GB+) |

> **Notă Whisper:** Modelul `medium` (implicit) procesează ~1h audio în 30–60 min pe CPU sau 3–5 min pe GPU NVIDIA. Dacă transcrierile sunt urgente, consideră un GPU sau modelul `small`.

### Hardware captură audio (client desktop)

Calitatea transcrierii și a diarizării vorbitorilor depinde direct de calitatea înregistrării audio.

| Scenariu | Dispozitiv recomandat | Rezultat |
|----------|-----------------------|----------|
| 1–2 persoane, birou | Microfon PC built-in | Bun |
| 3–5 persoane, birou mic | Microfon USB extern | Bun |
| 6–15 persoane, sală de ședință | **Microfon de conferință USB** | Bun |

**Microfoane de conferință testate și recomandate:**

| Model | Preț estimat | Acoperire | Vorbitori |
|-------|-------------|-----------|-----------|
| Anker PowerConf S3 | ~80€ | 5m rază | până la 8 |
| Jabra Speak 510 | ~100€ | 6m rază | până la 12 |
| Jabra Speak 750 | ~200€ | 7m rază + beamforming | până la 15 |

Microfoanele de conferință se conectează prin **USB** și apar automat în lista de dispozitive audio din clientul desktop — nu necesită configurare suplimentară.

> **De ce contează:** un microfon de PC captează toți vorbitorii la distanțe și volume diferite, ceea ce degradează semnificativ atât transcrierea cât și identificarea vorbitorilor. Un microfon de conferință cu beamforming rezolvă această problemă la nivel hardware.

### Software necesar

| Software | Versiune minimă | Note |
|----------|----------------|-------|
| **Linux** | Ubuntu 20.04 / Debian 11 | Recomandat Ubuntu 22.04 LTS |
| **Docker Engine** | 24.0+ | Instalat automat de `install.sh` |
| **Docker Compose** | 2.20+ (plugin v2) | Instalat automat de `install.sh` |
| **curl** | orice | Preinstalat pe majority distribuțiilor |
| **openssl** | orice | Necesar pentru generarea certificatelor |

> **Windows:** Instalează [Docker Desktop](https://www.docker.com/products/docker-desktop/) și [Git for Windows](https://git-scm.com), apoi rulează `.\install\install.ps1` — vezi [Secțiunea 2](#2-instalare-automată-recomandată).
> **macOS:** Instalează [Docker Desktop](https://www.docker.com/products/docker-desktop/) și urmează pașii din secțiunea [Instalare manuală](#3-instalare-manuală-pas-cu-pas).

### Porturi necesare

| Port | Protocol | Scop |
|------|----------|------|
| 80 | TCP | HTTP → redirect la HTTPS |
| 443 | TCP | HTTPS (interfața web) |
| 8080 | TCP | API direct (opțional, doar pentru debug) |

Asigură-te că aceste porturi sunt deschise în firewall-ul serverului.

---

## 2. Instalare automată (recomandată)

Funcționează pe **Ubuntu 20.04/22.04/24.04** și **Debian 11/12**.

### Pasul 1 — Descarcă codul sursă

```bash
git clone https://github.com/StefanJoita/MeetRec.git
cd MeetRec
```

### Pasul 2 — Rulează installer-ul

```bash
bash install/install.sh
```

Installer-ul va:
1. Verifica și instala Docker dacă lipsește
2. Cere informații de configurare de bază (domeniu, model Whisper)
3. Genera automat parole securizate și cheia JWT
4. Genera certificate SSL (self-signed sau Let's Encrypt)
5. Construi imaginile Docker (~20–40 min la prima rulare)
6. Porni toate serviciile
7. Crea contul de administrator

### Opțiune non-interactivă

Dacă rulezi în CI/CD sau vrei valorile implicite:

```bash
bash install/install.sh --non-interactive
```

---

## 3. Instalare manuală pas cu pas

Urmează acești pași dacă installer-ul automat nu funcționează sau rulezi pe macOS sau altă platformă neacoperită.

### Pasul 1 — Instalează Docker

**Ubuntu / Debian:**
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker   # sau delogheaza-te și loghează-te din nou
```

**Windows / macOS:**
Descarcă și instalează [Docker Desktop](https://www.docker.com/products/docker-desktop/).

Verifică instalarea:
```bash
docker --version          # Docker version 24.x.x
docker compose version    # Docker Compose version v2.x.x
```

### Pasul 2 — Descarcă codul sursă

```bash
git clone https://github.com/StefanJoita/MeetRec.git
cd MeetRec
```

### Pasul 3 — Configurează fișierul `.env`

```bash
cp .env.example .env
```

Deschide `.env` cu un editor și modifică **obligatoriu**:

```bash
# 1. Generează o cheie secretă unică pentru JWT
python3 -c "import secrets; print(secrets.token_hex(32))"
# → copiază rezultatul în JWT_SECRET_KEY

# 2. Alege o parolă pentru baza de date
# → modifică POSTGRES_PASSWORD și actualizează DATABASE_URL

# 3. Setează domeniul sau IP-ul serverului
SERVER_NAME=192.168.1.100     # sau meetrec.companie.ro
```

**Parametri importanți în `.env`:**

| Parametru | Valoare implicită | Descriere |
|-----------|-------------------|-----------|
| `JWT_SECRET_KEY` | *(de generat)* | Cheie secretă JWT — minim 32 caractere |
| `POSTGRES_PASSWORD` | `change_me_in_production` | Parolă bază de date |
| `SERVER_NAME` | `meeting-transcriber.local` | Domeniu sau IP server |
| `WHISPER_MODEL` | `medium` | Model transcriere: `tiny`/`base`/`small`/`medium`/`large` |
| `APP_ENV` | `development` | `production` dezactivează `/docs` OpenAPI |
| `WHISPER_PRIMARY_LANGUAGE` | `ro` | Limba principală pentru transcrieri |
| `RETENTION_DAYS` | `1095` | Zile după care înregistrările se șterg automat (3 ani) |

> ⚠️ **Niciodată** nu comite fișierul `.env` în Git. Conține secrete!

### Pasul 4 — Creează directoarele de date

```bash
mkdir -p data/inbox data/processed data/exports
```

### Pasul 5 — Configurează certificatele SSL

**Opțiunea A — Self-signed (LAN/intranet):**

```bash
# localhost sau IP
bash install/scripts/gen-self-signed.sh localhost
bash install/scripts/gen-self-signed.sh 192.168.1.100

# sau cu domeniu
bash install/scripts/gen-self-signed.sh meetrec.companie.ro
```

> Browserul va afișa un avertisment de securitate. Click **Avansat → Continuă**. Avertismentul poate fi eliminat adăugând certificatul în trusted store-ul sistemului.

**Opțiunea B — Let's Encrypt (server public cu domeniu real):**

Cerință: serverul trebuie să fie accesibil public pe portul 80.

```bash
bash install/scripts/gen-letsencrypt.sh meetrec.companie.ro admin@companie.ro
```

Certificatele Let's Encrypt sunt valabile 90 de zile. Pentru reînnoire automată, adaugă în crontab:
```bash
0 3 1 * * bash /calea/spre/MeetRec/install/scripts/gen-letsencrypt.sh meetrec.companie.ro admin@companie.ro && docker compose restart nginx
```

### Pasul 6 — Construiește imaginile Docker

```bash
docker compose build
```

> ⏱️ Prima construire durează **20–40 de minute** — imaginea STT worker include PyTorch (~3-5 GB de descărcat). Construirile ulterioare sunt mult mai rapide.

### Pasul 7 — Pornește serviciile

```bash
docker compose up -d
```

Verifică că toate serviciile sunt pornite:
```bash
docker compose ps
```

Toți serviciile trebuie să aibă statusul `running` sau `healthy`:

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

### Pasul 8 — Creează primul administrator

```bash
make create-admin
```

Sau manual:
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
        pwd = CryptContext(schemes=['bcrypt']).hash('PAROLA_TA')
        db.add(User(
            id=uuid.uuid4(),
            username='admin',
            email='admin@companie.ro',
            hashed_password=pwd,
            role='admin',
            is_active=True,
            force_password_change=True,
        ))
        await db.commit()
        print('Administrator creat.')

asyncio.run(run())
"
```

---

## 4. Configurare SSL

### Self-signed pentru mai multe hostname-uri / IP-uri

```bash
# IP specific
bash install/scripts/gen-self-signed.sh 192.168.1.100

# Domeniu intern
bash install/scripts/gen-self-signed.sh meetrec.local

# Aplică certificatele noi
docker compose restart nginx
```

### Adăugarea certificatului în trusted store (elimină avertismentul browserului)

**Windows:**
1. Deschide `nginx/ssl/fullchain.pem` → dublu click
2. **Instalare certificat** → **Mașina locală** → **Trusted Root Certification Authorities**

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

## 5. Primul login și configurare inițială

### Accesează aplicația

Deschide în browser: **`https://SERVERUL_TAU`**

> Dacă folosești certificate self-signed, browserul va afișa un avertisment. Click **Avansat → Continuă spre localhost (nesigur)**.

### Autentificare

1. Loghează-te cu credențialele de administrator create la pasul 8
2. La primul login, sistemul cere **schimbarea parolei** setate de administrator
3. Alege o parolă nouă sigură (minim 8 caractere)

### Adăugarea utilizatorilor

Din panoul **Admin → Utilizatori**:

| Rol | Permisiuni |
|-----|-----------|
| `admin` | Acces complet, gestionare utilizatori, ștergere înregistrări |
| `operator` | Upload înregistrări, gestionare participanți, export |
| `participant` | Vizualizare transcrieri la care au acces explicit |

### Primul fișier audio

1. Din inbox-ul de fișiere: copiază un fișier audio în `data/inbox/`
2. Sau prin interfața web: **Înregistrări → Adaugă**
3. Sistemul detectează automat fișierul și începe transcrierea
4. Statusul se actualizează în timp real: `queued` → `transcribing` → `completed`

### Așteptare la primul start al STT Worker

La primul start, Whisper descarcă modelul de transcriere:

| Model | Dimensiune | Timp descărcare (100 Mbps) |
|-------|------------|---------------------------|
| `tiny` | ~75 MB | ~6 sec |
| `base` | ~140 MB | ~11 sec |
| `small` | ~460 MB | ~37 sec |
| `medium` | ~1.5 GB | ~2 min |
| `large` | ~3 GB | ~4 min |

Urmărești progresul cu:
```bash
docker compose logs -f stt-worker
```

Modelul este descărcat la build time și este baked în imaginea Docker — la runtime nu e nevoie de internet.

---

## 6. Configurare avansată

### GPU NVIDIA (transcrieri mult mai rapide)

1. Instalează [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html):
```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

2. Decomentează blocul GPU în `docker-compose.yml`:
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

3. Rebuild și repornire:
```bash
docker compose build stt-worker
docker compose up -d stt-worker
```

### Schimbarea portului HTTPS

În `.env`:
```bash
NGINX_HTTPS_PORT=8443
```

Apoi:
```bash
docker compose up -d nginx
```

Aplicația va fi accesibilă la `https://server:8443`.

### Căutare semantică (AI)

La primul start, `search-indexer` descarcă modelul de embeddings (~120 MB). După ce a pornit cu succes, setează în `.env`:

```bash
HF_HUB_OFFLINE=1
```

Aceasta previne verificările online la fiecare repornire.

### Backup date

Datele importante sunt stocate în volume Docker:

```bash
# Backup bază de date
docker compose exec postgres pg_dump -U mt_user meeting_transcriber > backup_$(date +%Y%m%d).sql

# Backup fișiere audio (volumul Docker → director local)
docker run --rm -v meetrec_audio_storage:/data -v $(pwd):/backup \
    alpine tar czf /backup/audio_backup_$(date +%Y%m%d).tar.gz /data
```

---

## 7. Actualizare versiune

```bash
# 1. Descarcă noua versiune
git pull

# 2. Rebuild imaginile
docker compose build

# 3. Repornire cu migrări automate de bază de date
docker compose up -d
```

Migrările Alembic rulează automat la startup-ul containerului API.

---

## 8. Troubleshooting

### Serviciile nu pornesc

```bash
# Verifică statusul și logurile
docker compose ps
docker compose logs --tail=50 api
docker compose logs --tail=50 postgres
```

### Eroare: `DATABASE_URL must use postgresql+asyncpg://`

Verifică în `.env` că URL-ul bazei de date folosește protocolul corect:
```bash
DATABASE_URL=postgresql+asyncpg://mt_user:PAROLA@postgres:5432/meeting_transcriber
#                        ^^^^^^^^ obligatoriu
```

### Transcrierea rămâne în starea `queued`

STT worker-ul poate fi în curs de inițializare (descărcare model Whisper). Urmărești:
```bash
docker compose logs -f stt-worker
# Aștepți mesajul: "Whisper model loaded, waiting for jobs..."
```

### Browserul afișează "Connection refused" pe port 443

Verifică că nginx rulează și că portul 443 e liber pe server:
```bash
docker compose ps nginx
sudo lsof -i :443   # verifică dacă alt proces ocupă portul
```

### Eroare SSL: `certificate verify failed`

Dacă folosești certificate self-signed și un alt serviciu (nu browser) returnează eroarea:
```bash
# Verifică că certificatele există
ls -la nginx/ssl/

# Regenerează dacă lipsesc
bash install/scripts/gen-self-signed.sh localhost
docker compose restart nginx
```

### Nu pot accesa API-ul din browser (CORS)

Asigură-te că în `.env` `APP_ENV` e setat corect:
- `development` — CORS permisiv, `/docs` accesibil
- `production` — CORS restricționat la domeniu

### Loguri în timp real

```bash
make logs              # toate serviciile
make logs-api          # doar API
make logs-stt-worker   # doar worker transcriere
make logs-nginx        # accesuri și erori nginx
```

### Resetare completă (șterge toate datele!)

```bash
make clean-all   # oprește containerele și șterge volumele cu date
make setup       # reconfigurare
make build
make start
```

---

## Referință rapidă comenzi

```bash
make start           # pornește toate serviciile
make stop            # oprește toate serviciile
make restart         # repornire
make ps              # status servicii
make logs            # loguri în timp real
make build           # rebuild imagini Docker
make ssl-self-signed # regenerează certificate SSL self-signed
make create-admin    # creează utilizator administrator
make db-shell        # shell PostgreSQL
make redis-cli       # shell Redis
make api-shell       # shell în containerul API
make test            # rulează testele backend
```
