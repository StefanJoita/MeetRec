#!/usr/bin/env bash
# =============================================================
# install-offline.sh — instalează MeetRec pe un server FĂRĂ internet
# =============================================================
# Rulat din directorul pachetului (meetrec-offline-<versiune>/), ca root:
#   sudo ./install-offline.sh
#   sudo ./install-offline.sh --non-interactive    # valori implicite, fără întrebări
#
# Pași:
#   1. Verifică sistemul + integritatea pachetului (SHA256SUMS)
#   2. Instalează pachetele de sistem lipsă (iptables, nftables, openssl) și Docker Engine + Compose din packages/
#   3. Încarcă imaginile (docker load)
#   4. Generează .env cu secrete aleatoare
#   5. Certificate HTTPS (CA locală / self-signed / ale organizației)
#   6. Pornește serviciile
#   7. Configurează contul de administrator
#
# Re-rulare: sigură. .env, certificatele și datele existente sunt păstrate.
# Detalii: docs/INSTALL-OFFLINE.md
# =============================================================

set -euo pipefail

BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BUNDLE_DIR"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✅ $*${NC}"; }
info() { echo -e "${BLUE}ℹ️  $*${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $*${NC}"; }
err()  { echo -e "${RED}❌ $*${NC}" >&2; exit 1; }
step() { echo -e "\n${BOLD}━━━ $* ━━━${NC}"; }

INTERACTIVE=true
[[ "${1:-}" == "--non-interactive" ]] && INTERACTIVE=false

ask() {  # ask "Întrebare" "implicit" → răspuns
    local prompt="$1" default="$2" answer=""
    if [[ "$INTERACTIVE" == true ]]; then
        read -rp "  $prompt [$default]: " answer
    fi
    echo "${answer:-$default}"
}

env_get() { grep "^$1=" .env | tail -1 | cut -d= -f2- | sed 's/[[:space:]]*#.*//' | tr -d '"'; }
env_set() {  # env_set CHEIE valoare  (valoarea nu conține '|')
    if grep -q "^$1=" .env; then
        sed -i "s|^$1=.*|$1=$2|" .env
    else
        echo "$1=$2" >> .env
    fi
}
rand_hex() { od -An -tx1 -N"$1" /dev/urandom | tr -d ' \n'; }

VERSION=$(grep '^Versiune:' MANIFEST.txt 2>/dev/null | awk '{print $2}')
[[ -n "$VERSION" ]] || err "MANIFEST.txt lipsește — rulează scriptul din directorul pachetului offline."

echo -e "${BOLD}\n  MeetRec $VERSION — instalare offline\n${NC}"

# ── 1. Sistem + integritate ───────────────────────────────────
step "1/7 Verificare sistem și pachet"
[[ $EUID -eq 0 ]] || err "Rulează ca root: sudo ./install-offline.sh"
[[ "$(uname -m)" == "x86_64" ]] || err "Arhitectură nesuportată: $(uname -m). Pachetul este pentru x86_64 (amd64)."

. /etc/os-release 2>/dev/null || true
info "Sistem: ${PRETTY_NAME:-necunoscut}, kernel $(uname -r)"

MEM_GB=$(awk '/MemTotal/ {printf "%d", $2/1024/1024}' /proc/meminfo)
[[ $MEM_GB -ge 14 ]] || warn "RAM: ${MEM_GB} GB. Recomandat minim 16 GB pentru Whisper large-v3."
FREE_GB=$(df -BG --output=avail "$BUNDLE_DIR" | tail -1 | tr -dc '0-9')
[[ $FREE_GB -ge 40 ]] || warn "Spațiu liber: ${FREE_GB} GB. Recomandat minim 40 GB (imagini + înregistrări)."

if [[ -f SHA256SUMS ]]; then
    info "Verific integritatea fișierelor (poate dura 1-2 minute)..."
    sha256sum --quiet -c SHA256SUMS || err "Fișiere corupte/lipsă după transfer. Copiază din nou pachetul."
    ok "Integritate verificată (SHA256SUMS)"
else
    warn "SHA256SUMS lipsește — nu pot verifica integritatea."
fi

# ── 2. Pachete de sistem + Docker Engine ──────────────────────
step "2/7 Pachete de sistem și Docker Engine"
CODENAME="${VERSION_CODENAME:-}"

# Instalează din packages/system/<codename>/ DOAR pachetele care lipsesc de pe server
# (iptables, nftables, openssl + dependențe). Cele deja instalate nu sunt atinse.
install_system_packages() {
    local dir="packages/system/$CODENAME" deb name to_install=()
    [[ -n "$CODENAME" && -d "$dir" ]] && command -v dpkg >/dev/null || return 0
    for deb in "$dir"/*.deb; do
        name=$(dpkg-deb -f "$deb" Package)
        dpkg-query -W -f='${Status}' "$name" 2>/dev/null | grep -q "install ok installed" \
            || to_install+=("$deb")
    done
    if [[ ${#to_install[@]} -eq 0 ]]; then
        ok "Pachete de sistem: toate prezente"
        return 0
    fi
    info "Instalez ${#to_install[@]} pachete de sistem lipsă din $dir"
    dpkg -i "${to_install[@]}" >/dev/null \
        || err "Instalarea pachetelor de sistem a eșuat (vezi mesajele dpkg). Vezi docs/INSTALL-OFFLINE.md §11.1."
    ok "Pachete de sistem instalate: $(for d in "${to_install[@]}"; do dpkg-deb -f "$d" Package; done | tr '\n' ' ')"
}
install_system_packages

install_docker_static() {
    local tgz
    tgz=$(ls packages/docker/static/docker-*.tgz 2>/dev/null | head -1)
    [[ -n "$tgz" ]] || err "Nu există binare statice Docker în packages/docker/static/."
    info "Instalez binarele statice: $(basename "$tgz")"
    tar -xzf "$tgz" -C /tmp
    install -m 755 /tmp/docker/* /usr/bin/
    rm -rf /tmp/docker
    mkdir -p /usr/local/lib/docker/cli-plugins
    install -m 755 packages/docker/static/docker-compose-linux-x86_64 /usr/local/lib/docker/cli-plugins/docker-compose
    getent group docker >/dev/null || groupadd --system docker
    cat > /etc/systemd/system/containerd.service <<'EOF'
[Unit]
Description=containerd container runtime
After=network.target local-fs.target
[Service]
ExecStartPre=-/sbin/modprobe overlay
ExecStart=/usr/bin/containerd
Type=notify
Delegate=yes
KillMode=process
Restart=always
LimitNOFILE=infinity
TasksMax=infinity
[Install]
WantedBy=multi-user.target
EOF
    cat > /etc/systemd/system/docker.service <<'EOF'
[Unit]
Description=Docker Application Container Engine
After=network-online.target containerd.service
Wants=network-online.target
Requires=containerd.service
[Service]
Type=notify
ExecStart=/usr/bin/dockerd --containerd=/run/containerd/containerd.sock
ExecReload=/bin/kill -s HUP $MAINPID
Restart=always
LimitNOFILE=infinity
TasksMax=infinity
Delegate=yes
KillMode=process
[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
}

if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
    ok "Docker deja instalat: $(docker --version)"
else
    DEB_DIR="packages/docker/deb/$CODENAME"
    if [[ -n "$CODENAME" && -d "$DEB_DIR" ]] && command -v dpkg >/dev/null; then
        missing=()
        for dep in iptables nftables libseccomp2 libsystemd0; do
            dpkg -s "$dep" >/dev/null 2>&1 || missing+=("$dep")
        done
        if [[ ${#missing[@]} -gt 0 ]]; then
            err "Lipsesc pachetele de sistem: ${missing[*]} (nu sunt nici în packages/system/$CODENAME/). Vezi docs/INSTALL-OFFLINE.md §11.1."
        fi
        info "Instalez Docker din $DEB_DIR"
        dpkg -i "$DEB_DIR"/containerd.io_*.deb "$DEB_DIR"/docker-ce-cli_*.deb "$DEB_DIR"/docker-ce_*.deb \
                "$DEB_DIR"/docker-buildx-plugin_*.deb "$DEB_DIR"/docker-compose-plugin_*.deb
    else
        warn "Nu am pachete .deb pentru '${CODENAME:-necunoscut}' — folosesc binarele statice."
        install_docker_static
    fi
    systemctl enable --now containerd docker
    ok "Docker instalat: $(docker --version)"
fi
docker info >/dev/null 2>&1 || err "Docker daemon nu rulează: systemctl status docker"

# ── 3. Imagini ────────────────────────────────────────────────
step "3/7 Încărcare imagini Docker"
shopt -s nullglob
images=(images/*.tar.gz)
[[ ${#images[@]} -gt 0 ]] || err "Directorul images/ e gol."
for archive in "${images[@]}"; do
    info "docker load ← $(basename "$archive")"
    gunzip -c "$archive" | docker load >/dev/null
done
ok "${#images[@]} imagini încărcate"
docker image ls --format '  {{.Repository}}:{{.Tag}}  {{.Size}}' | grep -E 'meetrec/|pgvector|redis|nginx' || true

# ── 4. Configurare .env ───────────────────────────────────────
step "4/7 Configurare (.env)"
if [[ -f .env ]]; then
    ok ".env există — îl păstrez (secretele nu se regenerează)"
else
    cp .env.example .env
    chmod 600 .env
    DEFAULT_HOST=$(hostname -I 2>/dev/null | awk '{print $1}')
    SERVER_NAME=$(ask "Nume DNS sau IP al serverului (așa cum îl vor accesa utilizatorii)" "${DEFAULT_HOST:-localhost}")
    DB_PASSWORD=$(rand_hex 16)
    sed -i "s|change_me_in_production|${DB_PASSWORD}|g" .env      # POSTGRES_PASSWORD + DATABASE_URL
    env_set JWT_SECRET_KEY "$(rand_hex 32)"
    env_set REDIS_PASSWORD "$(rand_hex 24)"
    env_set SERVER_NAME "$SERVER_NAME"
    env_set APP_ENV production
    env_set MEETREC_VERSION "$VERSION"
    env_set HF_TOKEN ""
    WHISPER=$(grep '^Model Whisper:' MANIFEST.txt | awk '{print $3}')
    [[ -n "$WHISPER" ]] && env_set WHISPER_MODEL "$WHISPER"
    if grep -q '^Diarizare:[[:space:]]*da' MANIFEST.txt; then
        DIAR=$(ask "Activez diarizarea (identificarea vorbitorilor)? (true/false)" "true")
        env_set DIARIZATION_ENABLED "$DIAR"
    else
        env_set DIARIZATION_ENABLED false
    fi
    ok ".env generat (parole DB/Redis și cheie JWT aleatoare)"
fi
[[ "$(env_get MEETREC_VERSION)" == "$VERSION" ]] || {
    warn "MEETREC_VERSION din .env ($(env_get MEETREC_VERSION)) diferă de pachet ($VERSION) — actualizez."
    env_set MEETREC_VERSION "$VERSION"
}
SERVER_NAME=$(env_get SERVER_NAME)

# ── 5. Certificate HTTPS ──────────────────────────────────────
step "5/7 Certificate HTTPS"
if [[ -f nginx/ssl/fullchain.pem && -f nginx/ssl/privkey.pem ]]; then
    ok "Certificate existente în nginx/ssl/ — le păstrez"
else
    echo "  1) CA locală MeetRec (recomandat: clienții importă o singură dată meetrec-ca.crt)"
    echo "  2) Self-signed (avertisment în browser pe fiecare client)"
    echo "  3) Am certificatul organizației → îl copiez manual în nginx/ssl/ și re-rulez"
    choice=$(ask "Alege" "1")
    if [[ "$choice" == 1 || "$choice" == 2 ]]; then
        command -v openssl >/dev/null || err "openssl lipsește de pe server (pachetul nu are .deb-uri pentru acest sistem). Instalează openssl sau alege opțiunea 3."
    fi
    case "$choice" in
        1) bash install/certs/gen-local-ca.sh "$SERVER_NAME" ;;
        2) bash install/certs/gen-self-signed.sh "$SERVER_NAME" ;;
        *) echo "  Copiază certificatul (cu lanțul intermediar) ca nginx/ssl/fullchain.pem"
           echo "  și cheia privată ca nginx/ssl/privkey.pem, apoi rulează din nou acest script."
           exit 0 ;;
    esac
fi

# ── 6. Pornire servicii ───────────────────────────────────────
step "6/7 Pornire servicii"
mkdir -p data/inbox data/processed data/exports
# API rulează ca UID 1000 și scrie în data/inbox (bind mount)
chown 1000:1000 data/inbox

# frontend-network are subnet fix (FRONTEND_SUBNET): API-ul acceptă X-Forwarded-For doar din el.
# O rețea mt-frontend creată de o versiune anterioară (alt subnet) trebuie recreată.
WANT_SUBNET="$(env_get FRONTEND_SUBNET)"; WANT_SUBNET="${WANT_SUBNET:-172.30.10.0/24}"
CUR_SUBNET=$(docker network inspect mt-frontend --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}' 2>/dev/null || true)
if [[ -n "$CUR_SUBNET" && "$CUR_SUBNET" != "$WANT_SUBNET" ]]; then
    info "Rețeaua mt-frontend are subnetul $CUR_SUBNET (configurat: $WANT_SUBNET) — o recreez; volumele de date rămân."
    docker compose down
fi

docker compose up -d --no-build --pull never

info "Aștept ca API-ul să fie gata..."
for _ in $(seq 1 60); do
    if docker compose exec -T api curl -sf http://localhost:8080/health >/dev/null 2>&1; then
        API_OK=1; break
    fi
    sleep 3
done
[[ "${API_OK:-0}" == 1 ]] && ok "API pornit" || warn "API nu răspunde încă. Verifică: docker compose logs api"
info "STT worker încarcă modelul Whisper (1-3 minute). Urmărește: docker compose logs -f stt-worker"

# ── 7. Administrator ──────────────────────────────────────────
step "7/7 Cont administrator"
if [[ "$INTERACTIVE" == true && "${API_OK:-0}" == 1 ]]; then
    ADMIN_USER=$(ask "Username administrator" "admin")
    ADMIN_EMAIL=$(ask "Email administrator" "admin@${SERVER_NAME}")
    while :; do
        read -rsp "  Parolă (minim 8 caractere): " ADMIN_PASS; echo
        read -rsp "  Confirmă parola: " ADMIN_PASS2; echo
        [[ "$ADMIN_PASS" == "$ADMIN_PASS2" && ${#ADMIN_PASS} -ge 8 ]] && break
        warn "Parolele nu coincid sau sunt prea scurte."
    done
    if MEETREC_ADMIN_PASSWORD="$ADMIN_PASS" docker compose exec -T -e MEETREC_ADMIN_PASSWORD api \
        python -m src.cli.create_admin --username "$ADMIN_USER" --email "$ADMIN_EMAIL" \
        --update-existing --disable-default-operator; then
        ok "Administrator '$ADMIN_USER' configurat"
    else
        warn "Nu am putut configura administratorul. Manual: docker compose exec api python -m src.cli.create_admin --update-existing"
    fi
    unset ADMIN_PASS ADMIN_PASS2
else
    warn "Configurează administratorul manual:"
    echo "    docker compose exec api python -m src.cli.create_admin --username admin --email admin@firma.ro --update-existing --disable-default-operator"
    warn "Până atunci există conturile implicite admin/admin123 și operator/operator123 (schimbare parolă obligatorie)."
fi

# ── Sumar ─────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}${BOLD}  MeetRec $VERSION instalat${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  🌐 Aplicație:  ${BOLD}https://${SERVER_NAME}${NC}"
echo "  📁 Instalare:  $BUNDLE_DIR"
if [[ -f nginx/ssl/meetrec-ca.crt ]]; then
    echo "  🔐 CA pentru clienți: $BUNDLE_DIR/nginx/ssl/meetrec-ca.crt"
    echo "     (importă-l pe fiecare calculator — vezi docs/INSTALL-OFFLINE.md)"
fi
echo ""
echo "  Comenzi utile (din $BUNDLE_DIR):"
echo "    docker compose ps                 → status"
echo "    docker compose logs -f stt-worker → loguri transcriere"
echo "    docker compose restart            → repornire"
echo ""
