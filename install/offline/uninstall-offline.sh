#!/usr/bin/env bash
# =============================================================
# uninstall-offline.sh — dezinstalează MeetRec de pe serverul offline
# =============================================================
# Rulat din directorul pachetului (meetrec-offline-<versiune>/), ca root:
#   sudo ./uninstall-offline.sh                   # tot MeetRec: containere, imagini, DATE, .env, certificate
#   sudo ./uninstall-offline.sh --keep-certs      # ca mai sus, dar păstrează nginx/ssl/ (CA-ul importat pe clienți)
#   sudo ./uninstall-offline.sh --keep-data       # doar containere + imagini; datele, .env, certificatele rămân
#   sudo ./uninstall-offline.sh --remove-docker   # în plus, dezinstalează Docker Engine (instalare complet curată)
#   sudo ./uninstall-offline.sh --yes             # fără confirmare și fără backup (scripturi)
#
# După dezinstalare, fișierele pachetului (install-offline.sh, images/, packages/)
# rămân, deci o instalare de la zero se face direct: sudo ./install-offline.sh
#
# Ce NU se atinge: pachetele de sistem (iptables, nftables, openssl), /etc/hosts,
# certificatele CA importate pe calculatoarele clienților.
# Detalii: docs/INSTALL-OFFLINE.md §10.1
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

KEEP_DATA=false; KEEP_CERTS=false; REMOVE_DOCKER=false; ASSUME_YES=false
for arg in "$@"; do
    case "$arg" in
        --keep-data)     KEEP_DATA=true ;;
        --keep-certs)    KEEP_CERTS=true ;;
        --remove-docker) REMOVE_DOCKER=true ;;
        --yes|-y)        ASSUME_YES=true ;;
        -h|--help)       sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)               err "Opțiune necunoscută: $arg (vezi --help)" ;;
    esac
done
[[ "$KEEP_DATA" == true && "$REMOVE_DOCKER" == true ]] \
    && err "--keep-data și --remove-docker se exclud: fără Docker, volumele cu date se pierd."
[[ "$KEEP_DATA" == true ]] && KEEP_CERTS=true

[[ $EUID -eq 0 ]] || err "Rulează ca root: sudo ./uninstall-offline.sh"
[[ -f MANIFEST.txt ]] || err "MANIFEST.txt lipsește — rulează scriptul din directorul pachetului offline."
VERSION=$(grep '^Versiune:' MANIFEST.txt | awk '{print $2}')

echo -e "${BOLD}\n  MeetRec ${VERSION:-} — dezinstalare\n${NC}"

# Imaginile de bază din docker-compose.yml (încărcate tot de installer)
BASE_IMAGES=(pgvector/pgvector:pg15 redis:7-alpine nginx:1.25-alpine)
MT_VOLUMES="postgres_data redis_data audio_storage export_storage"

HAVE_DOCKER=false
if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
    HAVE_DOCKER=true
fi

# ── Inventar ──────────────────────────────────────────────────
step "1/5 Ce găsesc pe server"
containers=(); volumes=(); images=()
if [[ "$HAVE_DOCKER" == true ]]; then
    # Proiectele Compose MeetRec: numele fix "meetrec", proiectele containerelor mt-*
    # și cele care au volumul audio_storage (instalări vechi, din alte directoare)
    mapfile -t projects < <(
        { echo meetrec
          docker ps -a --filter name='^mt-' --format '{{.Label "com.docker.compose.project"}}'
          docker volume ls -q --filter label=com.docker.compose.volume=audio_storage \
              | xargs -r docker volume inspect --format '{{index .Labels "com.docker.compose.project"}}'
        } | grep -v '^$' | sort -u)

    mapfile -t containers < <(docker ps -a --filter name='^mt-' --format '{{.Names}}' | sort)
    for p in "${projects[@]}"; do
        for v in $MT_VOLUMES; do
            docker volume inspect "${p}_${v}" >/dev/null 2>&1 && volumes+=("${p}_${v}")
        done
    done
    mapfile -t images < <(
        docker image ls --format '{{.Repository}}:{{.Tag}}' \
            | grep -E "^meetrec/|^($(IFS='|'; echo "${BASE_IMAGES[*]}"))\$" | sort -u || true)

    echo "  Containere: ${containers[*]:-niciunul}"
    echo "  Imagini:    ${#images[@]} (${images[*]:-niciuna})"
    if [[ "$KEEP_DATA" == true ]]; then
        echo "  Volume:     ${volumes[*]:-niciunul} → PĂSTRATE"
    else
        echo "  Volume:     ${volumes[*]:-niciunul} → ȘTERSE"
        for v in "${volumes[@]}"; do
            echo "              $v  $(docker run --rm --entrypoint du -v "$v:/v:ro" redis:7-alpine -sh /v 2>/dev/null | cut -f1)"
        done
    fi
else
    warn "Docker nu rulează sau nu e instalat — sar peste containere, imagini și volume."
fi

if [[ "$KEEP_DATA" == true ]]; then
    echo "  Fișiere:    .env, nginx/ssl/, data/ → PĂSTRATE"
else
    echo "  Fișiere:    .env, data/ → ȘTERSE"
    if [[ "$KEEP_CERTS" == true ]]; then
        echo "              nginx/ssl/ → PĂSTRAT"
    else
        echo "              nginx/ssl/ → ȘTERS (clienții vor trebui să importe noul meetrec-ca.crt)"
    fi
fi
# Cum a fost instalat Docker: .deb (packages/docker/deb) sau binare statice (install_docker_static)
DEB_PKGS=(docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin docker-ce-rootless-extras)
docker_debs=()
for p in "${DEB_PKGS[@]}"; do
    dpkg -s "$p" >/dev/null 2>&1 && docker_debs+=("$p")
done
DOCKER_STATIC=false
grep -qs 'Docker Application Container Engine' /etc/systemd/system/docker.service && DOCKER_STATIC=true
if [[ "$REMOVE_DOCKER" == true && ${#docker_debs[@]} -eq 0 && "$DOCKER_STATIC" != true ]]; then
    warn "Docker nu a fost instalat de MeetRec (nici .deb, nici binare statice) — nu îl dezinstalez."
    REMOVE_DOCKER=false
fi
if [[ "$REMOVE_DOCKER" == true ]]; then
    echo "  Docker:     dezinstalat, inclusiv /var/lib/docker și /var/lib/containerd"
    others=$(docker ps -a --format '{{.Names}}' 2>/dev/null | grep -v '^mt-' || true)
    [[ -n "$others" ]] && warn "Se șterg și containerele altor aplicații: $(echo $others)"
fi

# ── Confirmare + backup ───────────────────────────────────────
step "2/5 Confirmare"
if [[ "$ASSUME_YES" != true ]]; then
    if [[ "$KEEP_DATA" != true ]]; then
        warn "Datele șterse (transcrieri, utilizatori, audio) NU pot fi recuperate fără backup."
        if docker ps --filter name='^mt-postgres$' --filter status=running -q 2>/dev/null | grep -q .; then
            read -rp "  Salvez întâi un backup al bazei de date? [D/n]: " ans
            if [[ ! "${ans:-D}" =~ ^[nN]$ ]]; then
                BK="$(dirname "$BUNDLE_DIR")/meetrec-backup-$(date +%F-%H%M%S).dump"
                docker exec mt-postgres sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$BK" \
                    || { rm -f "$BK"; err "Backup eșuat — nu continui."; }
                chmod 600 "$BK"
                ok "Backup bază de date: $BK ($(du -h "$BK" | cut -f1)). Restaurare: docs/INSTALL-OFFLINE.md §9.3"
            fi
        fi
    fi
    read -rp "  Scrie 'da' ca să continui: " confirm
    [[ "$confirm" == "da" ]] || { info "Anulat. Nu am modificat nimic."; exit 0; }
fi

# ── Containere, volume, rețele, imagini ───────────────────────
step "3/5 Containere, volume și imagini"
if [[ "$HAVE_DOCKER" == true ]]; then
    if [[ ${#containers[@]} -gt 0 ]]; then
        docker rm -f "${containers[@]}" >/dev/null
        ok "Containere șterse: ${#containers[@]}"
    fi
    for n in mt-backend mt-frontend; do
        docker network rm "$n" >/dev/null 2>&1 && ok "Rețea ștearsă: $n" || true
    done
    if [[ "$KEEP_DATA" != true && ${#volumes[@]} -gt 0 ]]; then
        docker volume rm "${volumes[@]}" >/dev/null
        ok "Volume șterse: ${volumes[*]}"
    fi
    if [[ ${#images[@]} -gt 0 ]]; then
        # o imagine de bază folosită de alt container rămâne (docker refuză ștergerea)
        for img in "${images[@]}"; do
            docker image rm "$img" >/dev/null 2>&1 || warn "Imagine păstrată (folosită de alt container): $img"
        done
        docker image prune -f >/dev/null
        ok "Imagini șterse"
    fi
fi

# ── Fișiere generate de installer ─────────────────────────────
step "4/5 Configurație și fișiere"
if [[ "$KEEP_DATA" == true ]]; then
    info "Păstrez .env, nginx/ssl/ și data/"
else
    rm -f .env
    rm -rf data
    mkdir -p data/inbox data/processed data/exports
    ok ".env și data/ șterse"
    if [[ "$KEEP_CERTS" != true ]]; then
        find nginx/ssl -mindepth 1 -delete 2>/dev/null || true
        ok "Certificate șterse din nginx/ssl/"
    fi
fi

# ── Docker Engine ─────────────────────────────────────────────
step "5/5 Docker Engine"
if [[ "$REMOVE_DOCKER" != true ]]; then
    info "Docker rămâne instalat (pentru dezinstalare: --remove-docker)"
else
    for unit in docker.socket docker containerd; do
        systemctl disable --now "$unit" >/dev/null 2>&1 || true
    done
    if [[ ${#docker_debs[@]} -gt 0 ]]; then
        dpkg --purge "${docker_debs[@]}" >/dev/null
        ok "Pachete Docker dezinstalate: ${docker_debs[*]}"
    else
        # instalat de install-offline.sh din binarele statice
        rm -f /usr/bin/{docker,dockerd,docker-init,docker-proxy,containerd,containerd-shim-runc-v2,ctr,runc}
        rm -f /usr/local/lib/docker/cli-plugins/docker-compose
        rm -f /etc/systemd/system/docker.service /etc/systemd/system/containerd.service
        systemctl daemon-reload
        ok "Binarele statice Docker și serviciile systemd șterse"
    fi
    rm -rf /var/lib/docker /var/lib/containerd
    ok "/var/lib/docker și /var/lib/containerd șterse"
fi

# ── Sumar ─────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}${BOLD}  MeetRec dezinstalat${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  Instalare de la zero:  cd $BUNDLE_DIR && sudo ./install-offline.sh"
echo "  Ștergere completă:     sudo rm -rf $BUNDLE_DIR"
for d in "$(dirname "$BUNDLE_DIR")"/meetrec-offline-*/; do
    d="${d%/}"
    [[ "$d" != "$BUNDLE_DIR" && -f "$d/.env" ]] && warn "Altă instalare cu .env: $d (rulează și acolo scriptul sau șterge directorul)"
done
echo ""
