#!/usr/bin/env bash
# =============================================================
# install.sh — Installer MeetRec pe mediu fresh
# =============================================================
# Platforme suportate: Ubuntu 20.04/22.04/24.04, Debian 11/12
# Cerințe: bash 4+, curl, sudo
#
# Folosire:
#   bash install/online/install.sh
#   bash install/online/install.sh --non-interactive   (folosește valorile default)
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # install/online/
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"                    # rădăcina repo-ului

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

if [[ -f "$REPO_ROOT/.env" ]]; then
    warn ".env există deja."
    if [[ "$INTERACTIVE" == true ]]; then
        read -rp "Îl suprascriu? [y/N] " ans
        [[ "${ans:-N}" =~ ^[Yy]$ ]] || { info "Păstrez .env existent. Sar la pasul următor."; skip_env=true; }
    fi
fi

if [[ "${skip_env:-false}" != true ]]; then
    cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"

    # Generează JWT secret automat
    JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || \
                 openssl rand -hex 32)

    # Generează parole DB + Redis automat (hex → URL-safe în DATABASE_URL/REDIS_URL)
    DB_PASSWORD=$(openssl rand -hex 16)
    REDIS_PASSWORD=$(openssl rand -hex 24)

    # Valori default pentru configurare interactivă
    SERVER_NAME="localhost"
    WHISPER_MODEL="large-v3"
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
        echo "    medium → echilibrat      calitate foarte bună (~1.5GB, ~5GB RAM)"
        echo "    large-v3 → recomandat,   calitate maximă   (~3GB, ~10GB RAM)"
        read -rp "  Model Whisper [large-v3]: " _model
        [[ -n "$_model" ]] && WHISPER_MODEL="$_model"

        echo ""
        read -rp "  Mediu (development/production) [production]: " _env
        [[ -n "$_env" ]] && APP_ENV="$_env"
    fi

    # Aplică valorile în .env
    sed -i "s|your-secret-key-min-32-chars-change-this|${JWT_SECRET}|g" "$REPO_ROOT/.env"
    sed -i "s|change_me_in_production|${DB_PASSWORD}|g" "$REPO_ROOT/.env"
    sed -i "s|^REDIS_PASSWORD=.*|REDIS_PASSWORD=${REDIS_PASSWORD}|" "$REPO_ROOT/.env"
    sed -i "s|SERVER_NAME=.*|SERVER_NAME=${SERVER_NAME}|g" "$REPO_ROOT/.env"
    sed -i "s|WHISPER_MODEL=.*|WHISPER_MODEL=${WHISPER_MODEL}|g" "$REPO_ROOT/.env"
    sed -i "s|APP_ENV=.*|APP_ENV=${APP_ENV}|g" "$REPO_ROOT/.env"
    # Actualizează DATABASE_URL cu parola nouă
    sed -i "s|mt_user:change_me_in_production|mt_user:${DB_PASSWORD}|g" "$REPO_ROOT/.env"

    ok ".env configurat (SERVER_NAME=$SERVER_NAME, MODEL=$WHISPER_MODEL)"
fi

# Citește SERVER_NAME din .env pentru pașii următori
SERVER_NAME=$(grep '^SERVER_NAME=' "$REPO_ROOT/.env" | cut -d= -f2 | tr -d '"')

# ── Certificate SSL ───────────────────────────────────────────
step "4/7 Certificate SSL"

SSL_DIR="$REPO_ROOT/nginx/ssl"
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
        bash "$REPO_ROOT/install/certs/gen-letsencrypt.sh" "$SERVER_NAME" "${LE_EMAIL:-admin@${SERVER_NAME}}"
    else
        info "Generez certificate self-signed pentru: $SERVER_NAME..."
        bash "$REPO_ROOT/install/certs/gen-self-signed.sh" "$SERVER_NAME"
    fi
fi

ok "Certificate SSL gata"

# ── Creare directoare date ────────────────────────────────────
step "5/7 Directoare"

mkdir -p "$REPO_ROOT/data/inbox" \
         "$REPO_ROOT/data/processed" \
         "$REPO_ROOT/data/exports"
touch "$REPO_ROOT/data/inbox/.gitkeep" \
      "$REPO_ROOT/data/processed/.gitkeep" \
      "$REPO_ROOT/data/exports/.gitkeep" 2>/dev/null || true

ok "Directoare create: data/inbox, data/processed, data/exports"

# ── Build + Start ─────────────────────────────────────────────
step "6/7 Build și pornire servicii"

cd "$REPO_ROOT"

# Modelele ML sunt incluse în imagini → trebuie descărcate ÎNAINTE de build
if ls -d services/stt-worker/models/whisper/models--Systran--faster-whisper-* &>/dev/null \
   && ls -d services/search-indexer/models/models--sentence-transformers--* &>/dev/null; then
    ok "Modele ML găsite deja (services/*/models/)"
else
    info "Descarc modelele ML (Whisper, aliniere, embeddings; ~4-5 GB)..."
    _model=$(grep '^WHISPER_MODEL=' .env | cut -d= -f2 | tr -d '"')
    _hf_token=$(grep '^HF_TOKEN=' .env | cut -d= -f2- | tr -d '"')
    _extra=()
    if [[ -z "$_hf_token" ]]; then
        warn "HF_TOKEN gol în .env → modelul de diarizare (pyannote) NU va fi inclus."
        _extra=(--skip-diarization)
    fi
    HF_TOKEN="$_hf_token" bash "$REPO_ROOT/install/models/download-models-docker.sh" \
        --whisper-model "${_model:-large-v3}" "${_extra[@]}"
fi

info "Construiesc imaginile Docker... (prima construire: 20-40 min)"
info "Poți urmări progresul cu: docker compose logs -f"
echo ""

docker compose build

info "Pornesc serviciile..."
docker compose up -d

# Așteaptă ca API-ul să fie healthy (portul 8080 nu e expus pe host → verificăm din container)
info "Aștept ca API-ul să fie gata..."
MAX_WAIT=180
WAITED=0
until docker compose exec -T api curl -sf http://localhost:8080/health &>/dev/null || [[ $WAITED -ge $MAX_WAIT ]]; do
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
    read -rsp "  Parolă (minim 8 caractere): " ADMIN_PASS
    echo ""

    if [[ -n "$ADMIN_EMAIL" && -n "$ADMIN_PASS" ]]; then
        # Parola e transmisă prin variabilă de mediu (nu apare în linia de comandă).
        # --update-existing: suprascrie parola implicită a contului "admin" din init.sql.
        # --disable-default-operator: dezactivează "operator"/"operator123" din init.sql.
        if MEETREC_ADMIN_PASSWORD="$ADMIN_PASS" docker compose exec -T -e MEETREC_ADMIN_PASSWORD api \
            python -m src.cli.create_admin --username "$ADMIN_USER" --email "$ADMIN_EMAIL" \
            --update-existing --disable-default-operator; then
            ok "Administrator '$ADMIN_USER' configurat"
        else
            warn "Nu am putut crea administratorul automat. Rulează manual: make create-admin"
        fi
    fi
    unset ADMIN_PASS
else
    info "Mod non-interactiv: creează administratorul cu: make create-admin"
    warn "Până atunci există conturile implicite admin/admin123 și operator/operator123 (schimbare parolă obligatorie la login)."
fi

# ── Sumar final ───────────────────────────────────────────────
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}${BOLD}  MeetRec instalat cu succes!${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  🌐 Aplicație:    ${BOLD}https://${SERVER_NAME}${NC}"
if [[ "$(grep 'APP_ENV' "$REPO_ROOT/.env" | cut -d= -f2)" == "development" ]]; then
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
if [[ "${SSL_TYPE:-}" == "self-signed" ]]; then
echo -e "  ${YELLOW}⚠️  Certificate self-signed: browserul va afișa avertisment.${NC}"
echo -e "  ${YELLOW}   Chrome/Edge: click 'Advanced' → 'Proceed to ${SERVER_NAME}'${NC}"
echo ""
fi
