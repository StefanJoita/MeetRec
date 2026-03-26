#!/usr/bin/env bash
# =============================================================
# install.sh — Installer MeetRec pe mediu fresh
# =============================================================
# Platforme suportate: Ubuntu 20.04/22.04/24.04, Debian 11/12
# Cerințe: bash 4+, curl, sudo
#
# Folosire:
#   bash install.sh
#   bash install.sh --non-interactive   (folosește valorile default)
# =============================================================

set -euo pipefail

# ── Culori ────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✅ $*${NC}"; }
info() { echo -e "${BLUE}ℹ️  $*${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $*${NC}"; }
err()  { echo -e "${RED}❌ $*${NC}" >&2; exit 1; }
step() { echo -e "\n${BOLD}━━━ $* ━━━${NC}"; }

INTERACTIVE=true
[[ "${1:-}" == "--non-interactive" ]] && INTERACTIVE=false

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Banner ────────────────────────────────────────────────────
echo -e "${BOLD}"
echo "  ███╗   ███╗███████╗███████╗████████╗██████╗ ███████╗ ██████╗"
echo "  ████╗ ████║██╔════╝██╔════╝╚══██╔══╝██╔══██╗██╔════╝██╔════╝"
echo "  ██╔████╔██║█████╗  █████╗     ██║   ██████╔╝█████╗  ██║"
echo "  ██║╚██╔╝██║██╔══╝  ██╔══╝     ██║   ██╔══██╗██╔══╝  ██║"
echo "  ██║ ╚═╝ ██║███████╗███████╗   ██║   ██║  ██║███████╗╚██████╗"
echo "  ╚═╝     ╚═╝╚══════╝╚══════╝   ╚═╝   ╚═╝  ╚═╝╚══════╝ ╚═════╝"
echo -e "${NC}"
echo -e "  Platforma self-hosted de transcriere ședințe\n"

# ── Verifică OS ───────────────────────────────────────────────
step "1/7 Verificare sistem"

if [[ "$OSTYPE" != "linux-gnu"* ]]; then
    err "Acest script rulează doar pe Linux (Ubuntu/Debian). Pe Windows folosește WSL2."
fi

if command -v lsb_release &>/dev/null; then
    DISTRO=$(lsb_release -si 2>/dev/null || echo "Unknown")
    VERSION=$(lsb_release -sr 2>/dev/null || echo "")
    info "Distribuție detectată: $DISTRO $VERSION"
    if [[ "$DISTRO" != "Ubuntu" && "$DISTRO" != "Debian" ]]; then
        warn "Distribuție netestată ($DISTRO). Instalarea poate eșua. Ubuntu/Debian recomandat."
    fi
fi

# Verifică că nu rulează ca root direct
if [[ $EUID -eq 0 ]]; then
    warn "Rulezi ca root. Recomandat: rulează ca utilizator normal cu sudo disponibil."
fi

ok "Sistem verificat"

# ── Instalare Docker ──────────────────────────────────────────
step "2/7 Docker"

install_docker() {
    info "Instalez Docker Engine..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    ok "Docker instalat"
    warn "Ai fost adăugat în grupul 'docker'. Loghează-te din nou sau rulează: newgrp docker"
}

if ! command -v docker &>/dev/null; then
    if [[ "$INTERACTIVE" == true ]]; then
        read -rp "Docker nu este instalat. Îl instalez acum? [Y/n] " ans
        [[ "${ans:-Y}" =~ ^[Yy]$ ]] && install_docker || err "Docker este necesar. Instalează-l manual: https://docs.docker.com/engine/install/"
    else
        install_docker
    fi
else
    DOCKER_VER=$(docker --version | grep -oP '\d+\.\d+\.\d+' | head -1)
    ok "Docker găsit: v$DOCKER_VER"
fi

# Verifică Docker Compose (plugin v2)
if ! docker compose version &>/dev/null; then
    info "Instalez Docker Compose plugin..."
    sudo apt-get install -y docker-compose-plugin 2>/dev/null || \
        err "Nu am putut instala docker-compose-plugin. Instalează manual: https://docs.docker.com/compose/install/"
    ok "Docker Compose instalat"
else
    COMPOSE_VER=$(docker compose version --short 2>/dev/null || echo "unknown")
    ok "Docker Compose găsit: v$COMPOSE_VER"
fi

# ── Configurare .env ──────────────────────────────────────────
step "3/7 Configurare"

if [[ -f "$SCRIPT_DIR/.env" ]]; then
    warn ".env există deja."
    if [[ "$INTERACTIVE" == true ]]; then
        read -rp "Îl suprascriu? [y/N] " ans
        [[ "${ans:-N}" =~ ^[Yy]$ ]] || { info "Păstrez .env existent. Sar la pasul următor."; skip_env=true; }
    fi
fi

if [[ "${skip_env:-false}" != true ]]; then
    cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"

    # Generează JWT secret automat
    JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || \
                 openssl rand -hex 32)

    # Generează parolă DB automată
    DB_PASSWORD=$(openssl rand -base64 24 | tr -dc 'a-zA-Z0-9' | head -c 24)

    # Valori default pentru configurare interactivă
    SERVER_NAME="localhost"
    WHISPER_MODEL="medium"
    APP_ENV="production"

    if [[ "$INTERACTIVE" == true ]]; then
        echo ""
        echo "  Configurare de bază (Enter = valoare default)"
        echo "  ─────────────────────────────────────────────"
        read -rp "  Domeniu sau IP server [localhost]: " _server_name
        [[ -n "$_server_name" ]] && SERVER_NAME="$_server_name"

        echo ""
        echo "  Model Whisper (afectează calitatea și viteza transcrierilor):"
        echo "    tiny   → cel mai rapid,  calitate scăzută  (~75MB)"
        echo "    base   → rapid,          calitate OK       (~140MB)"
        echo "    small  → echilibrat      calitate bună     (~460MB)"
        echo "    medium → recomandat      calitate foarte bună (~1.5GB)"
        echo "    large  → cel mai lent,   calitate maximă   (~3GB)"
        read -rp "  Model Whisper [medium]: " _model
        [[ -n "$_model" ]] && WHISPER_MODEL="$_model"

        echo ""
        read -rp "  Mediu (development/production) [production]: " _env
        [[ -n "$_env" ]] && APP_ENV="$_env"
    fi

    # Aplică valorile în .env
    sed -i "s|your-secret-key-min-32-chars-change-this|${JWT_SECRET}|g" "$SCRIPT_DIR/.env"
    sed -i "s|change_me_in_production|${DB_PASSWORD}|g" "$SCRIPT_DIR/.env"
    sed -i "s|SERVER_NAME=.*|SERVER_NAME=${SERVER_NAME}|g" "$SCRIPT_DIR/.env"
    sed -i "s|WHISPER_MODEL=.*|WHISPER_MODEL=${WHISPER_MODEL}|g" "$SCRIPT_DIR/.env"
    sed -i "s|APP_ENV=.*|APP_ENV=${APP_ENV}|g" "$SCRIPT_DIR/.env"
    # Actualizează DATABASE_URL cu parola nouă
    sed -i "s|mt_user:change_me_in_production|mt_user:${DB_PASSWORD}|g" "$SCRIPT_DIR/.env"

    ok ".env configurat (SERVER_NAME=$SERVER_NAME, MODEL=$WHISPER_MODEL)"
fi

# Citește SERVER_NAME din .env pentru pașii următori
SERVER_NAME=$(grep '^SERVER_NAME=' "$SCRIPT_DIR/.env" | cut -d= -f2 | tr -d '"')

# ── Certificate SSL ───────────────────────────────────────────
step "4/7 Certificate SSL"

SSL_DIR="$SCRIPT_DIR/nginx/ssl"
mkdir -p "$SSL_DIR"

if [[ -f "$SSL_DIR/fullchain.pem" && -f "$SSL_DIR/privkey.pem" ]]; then
    ok "Certificate SSL găsite deja în nginx/ssl/"
else
    SSL_TYPE="self-signed"
    if [[ "$INTERACTIVE" == true ]]; then
        echo ""
        echo "  Tip certificate SSL:"
        echo "    1) Self-signed  → pentru LAN/intranet (browserul va afișa avertisment)"
        echo "    2) Let's Encrypt → pentru servere publice cu domeniu real"
        read -rp "  Alege [1]: " _ssl_choice
        [[ "${_ssl_choice:-1}" == "2" ]] && SSL_TYPE="letsencrypt"
    fi

    if [[ "$SSL_TYPE" == "letsencrypt" ]]; then
        if [[ "$INTERACTIVE" == true ]]; then
            read -rp "  Email pentru notificări Let's Encrypt: " LE_EMAIL
        fi
        info "Obțin certificate Let's Encrypt pentru: $SERVER_NAME..."
        bash "$SCRIPT_DIR/scripts/gen-letsencrypt.sh" "$SERVER_NAME" "${LE_EMAIL:-admin@${SERVER_NAME}}"
    else
        info "Generez certificate self-signed pentru: $SERVER_NAME..."
        bash "$SCRIPT_DIR/scripts/gen-self-signed.sh" "$SERVER_NAME"
    fi
fi

ok "Certificate SSL gata"

# ── Creare directoare date ────────────────────────────────────
step "5/7 Directoare"

mkdir -p "$SCRIPT_DIR/data/inbox" \
         "$SCRIPT_DIR/data/processed" \
         "$SCRIPT_DIR/data/exports"
touch "$SCRIPT_DIR/data/inbox/.gitkeep" \
      "$SCRIPT_DIR/data/processed/.gitkeep" \
      "$SCRIPT_DIR/data/exports/.gitkeep" 2>/dev/null || true

ok "Directoare create: data/inbox, data/processed, data/exports"

# ── Build + Start ─────────────────────────────────────────────
step "6/7 Build și pornire servicii"

info "Construiesc imaginile Docker... (prima construire: 20-40 min)"
info "Poți urmări progresul cu: docker compose logs -f"
echo ""

cd "$SCRIPT_DIR"
docker compose build

info "Pornesc serviciile..."
docker compose up -d

# Așteaptă ca API-ul să fie healthy
info "Aștept ca API-ul să fie gata..."
MAX_WAIT=120
WAITED=0
until curl -sf http://localhost:8080/health &>/dev/null || [[ $WAITED -ge $MAX_WAIT ]]; do
    sleep 3
    WAITED=$((WAITED + 3))
    echo -n "."
done
echo ""

if [[ $WAITED -ge $MAX_WAIT ]]; then
    warn "API-ul nu a răspuns în ${MAX_WAIT}s. Verifică: docker compose logs api"
else
    ok "API pornit"
fi

# ── Creare administrator ──────────────────────────────────────
step "7/7 Administrator inițial"

if [[ "$INTERACTIVE" == true ]]; then
    echo ""
    echo "  Creează contul de administrator:"
    read -rp "  Username [admin]: " ADMIN_USER
    ADMIN_USER="${ADMIN_USER:-admin}"
    read -rp "  Email: " ADMIN_EMAIL
    read -rsp "  Parolă: " ADMIN_PASS
    echo ""

    if [[ -n "$ADMIN_EMAIL" && -n "$ADMIN_PASS" ]]; then
        # Creează admin direct în DB prin containerul API
        docker compose exec -T api python3 -c "
import asyncio, sys
sys.path.insert(0, '/app')
from src.database import AsyncSessionLocal
from src.models.audit_log import User
from passlib.context import CryptContext
from sqlalchemy import select
import uuid

pwd_ctx = CryptContext(schemes=['bcrypt'])

async def create_admin():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.username == '$ADMIN_USER'))
        existing = result.scalar_one_or_none()
        if existing:
            print('EXISTS')
            return
        user = User(
            id=uuid.uuid4(),
            username='$ADMIN_USER',
            email='$ADMIN_EMAIL',
            hashed_password=pwd_ctx.hash('$ADMIN_PASS'),
            role='admin',
            is_active=True,
            force_password_change=False,
        )
        db.add(user)
        await db.commit()
        print('CREATED')

asyncio.run(create_admin())
" 2>/dev/null && ok "Administrator '$ADMIN_USER' creat" || \
        warn "Nu am putut crea administratorul automat. Rulează manual: make create-admin"
    fi
else
    info "Mod non-interactiv: creează administratorul cu: make create-admin"
fi

# ── Sumar final ───────────────────────────────────────────────
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}${BOLD}  MeetRec instalat cu succes!${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  🌐 Aplicație:    ${BOLD}https://${SERVER_NAME}${NC}"
if [[ "$(grep 'APP_ENV' "$SCRIPT_DIR/.env" | cut -d= -f2)" == "development" ]]; then
echo -e "  📖 API Docs:     ${BOLD}http://${SERVER_NAME}:8080/docs${NC}"
fi
echo ""
echo "  Comenzi utile:"
echo "    make logs          → urmărire loguri în timp real"
echo "    make ps            → status servicii"
echo "    make stop          → oprire"
echo "    make restart       → repornire"
echo "    make create-admin  → creează utilizator admin nou"
echo ""
if [[ "$SSL_TYPE" == "self-signed" ]]; then
echo -e "  ${YELLOW}⚠️  Certificate self-signed: browserul va afișa avertisment.${NC}"
echo -e "  ${YELLOW}   Chrome/Edge: click 'Advanced' → 'Proceed to ${SERVER_NAME}'${NC}"
echo ""
fi
