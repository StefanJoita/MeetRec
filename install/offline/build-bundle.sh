#!/usr/bin/env bash
# =============================================================
# build-bundle.sh — construiește pachetul de instalare OFFLINE
# =============================================================
# Rulat pe o mașină CU internet și Docker (Linux, sau Windows cu Git Bash
# + Docker Desktop). Rezultat:
#
#   dist/meetrec-offline-<versiune>/
#   ├── install-offline.sh           ← rulat pe serverul fără internet
#   ├── docker-compose.yml           ← fără secțiuni build:, pull_policy: never
#   ├── .env.example
#   ├── database/init.sql
#   ├── nginx/ (configurație + ssl/)
#   ├── install/certs/               ← certificate (CA locală / self-signed)
#   ├── images/*.tar.gz              ← toate imaginile Docker (docker save)
#   ├── packages/docker/             ← Docker Engine + Compose (.deb + static)
#   ├── docs/INSTALL-OFFLINE.md
#   ├── MANIFEST.txt                 ← versiuni, imagini, modele
#   └── SHA256SUMS                   ← verificare integritate după transfer
#   dist/meetrec-offline-<versiune>.tar   ← arhiva de transferat
#
# Folosire:
#   bash install/offline/build-bundle.sh                    # versiunea din .env sau 1.0.0
#   MEETREC_VERSION=1.2.0 bash install/offline/build-bundle.sh
#   SKIP_DOCKER_PACKAGES=1 bash install/offline/build-bundle.sh   # serverul are deja Docker
#
# Prerechizite: docker (cu compose v2), curl, gzip, sha256sum, tar.
# Modelele ML: dacă lipsesc, sunt descărcate automat (HF_TOKEN din .env pentru diarizare).
# =============================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

ok()   { echo -e "\033[0;32m✅ $*\033[0m"; }
info() { echo -e "\033[0;34mℹ️  $*\033[0m"; }
warn() { echo -e "\033[1;33m⚠️  $*\033[0m"; }
err()  { echo -e "\033[0;31m❌ $*\033[0m" >&2; exit 1; }
step() { echo -e "\n\033[1m━━━ $* ━━━\033[0m"; }

env_value() { [[ -f .env ]] && grep "^$1=" .env | tail -1 | cut -d= -f2- | sed 's/[[:space:]]*#.*//' | tr -d '"\r' || true; }

VERSION="${MEETREC_VERSION:-$(env_value MEETREC_VERSION)}"
VERSION="${VERSION:-1.0.0}"
WHISPER_MODEL="${WHISPER_MODEL:-$(env_value WHISPER_MODEL)}"
WHISPER_MODEL="${WHISPER_MODEL:-large-v3}"
export MEETREC_VERSION="$VERSION"

NAME="meetrec-offline-$VERSION"
DIST="$REPO_ROOT/dist"
OUT="$DIST/$NAME"
PLATFORM=linux/amd64

BUILT_SERVICES=(api ingest stt-worker frontend audit-retention search-indexer)
BASE_IMAGES=(pgvector/pgvector:pg15 redis:7-alpine nginx:1.25-alpine)

# ── 1. Verificări ─────────────────────────────────────────────
step "1/7 Verificări"
command -v docker >/dev/null || err "Docker nu este instalat."
docker info >/dev/null 2>&1 || err "Docker daemon nu rulează."
docker compose version >/dev/null 2>&1 || err "Lipsește Docker Compose v2 (docker compose)."
for cmd in curl gzip sha256sum tar; do command -v "$cmd" >/dev/null || err "Lipsește comanda: $cmd"; done
ok "Docker $(docker version --format '{{.Server.Version}}'), versiune pachet: $VERSION, Whisper: $WHISPER_MODEL"

# ── 2. Modele ML ──────────────────────────────────────────────
step "2/7 Modele ML"
if ls -d services/stt-worker/models/whisper/models--Systran--faster-whisper-* >/dev/null 2>&1 \
   && ls -d services/search-indexer/models/models--sentence-transformers--* >/dev/null 2>&1; then
    ok "Modele găsite în services/*/models/"
else
    info "Descarc modelele (Whisper $WHISPER_MODEL, aliniere, embeddings)..."
    extra=()
    [[ -z "$(env_value HF_TOKEN)" && -z "${HF_TOKEN:-}" ]] && extra=(--skip-diarization)
    HF_TOKEN="${HF_TOKEN:-$(env_value HF_TOKEN)}" \
        bash install/models/download-models-docker.sh --whisper-model "$WHISPER_MODEL" "${extra[@]}"
fi
if ls -d services/stt-worker/models/huggingface/hub/models--pyannote--* >/dev/null 2>&1; then
    DIARIZATION_INCLUDED=da
else
    DIARIZATION_INCLUDED=nu
    warn "Modelul de diarizare (pyannote) NU e inclus — DIARIZATION_ENABLED trebuie să rămână false."
fi

# ── 3. Build imagini ──────────────────────────────────────────
step "3/7 Build imagini ($PLATFORM)"
export DOCKER_DEFAULT_PLATFORM=$PLATFORM
# REDIS_PASSWORD etc. nu contează la build, dar compose validează interpolarea
REDIS_PASSWORD="${REDIS_PASSWORD:-build-only}" docker compose build "${BUILT_SERVICES[@]}"
for img in "${BASE_IMAGES[@]}"; do
    docker pull --platform "$PLATFORM" "$img"
done
ok "Imagini construite"

# ── 4. Export imagini ─────────────────────────────────────────
step "4/7 Export imagini (docker save)"
rm -rf "$OUT"
mkdir -p "$OUT/images"
ALL_IMAGES=()
for svc in "${BUILT_SERVICES[@]}"; do ALL_IMAGES+=("meetrec/$svc:$VERSION"); done
ALL_IMAGES+=("${BASE_IMAGES[@]}")
for img in "${ALL_IMAGES[@]}"; do
    file="$OUT/images/$(echo "$img" | tr '/:' '__').tar.gz"
    info "$img → images/$(basename "$file")"
    docker save "$img" | gzip -1 > "$file"
done
ok "Imagini exportate ($(du -sh "$OUT/images" | cut -f1))"

# ── 5. Pachete Docker Engine ──────────────────────────────────
step "5/7 Docker Engine pentru server"
if [[ "${SKIP_DOCKER_PACKAGES:-0}" == "1" ]]; then
    warn "SKIP_DOCKER_PACKAGES=1 — pachetele Docker nu sunt incluse."
else
    bash install/offline/download-docker-packages.sh "$DIST/packages/docker"
    mkdir -p "$OUT/packages"
    cp -r "$DIST/packages/docker" "$OUT/packages/"
fi

# ── 6. Fișiere de deployment ──────────────────────────────────
step "6/7 Fișiere de deployment"
mkdir -p "$OUT/database" "$OUT/nginx/ssl" "$OUT/install/certs" "$OUT/docs" \
         "$OUT/data/inbox" "$OUT/data/processed" "$OUT/data/exports"
cp .env.example "$OUT/.env.example"
cp database/init.sql "$OUT/database/"
cp nginx/nginx.conf "$OUT/nginx/"
cp -r nginx/conf.d "$OUT/nginx/"
cp install/certs/gen-local-ca.sh install/certs/gen-self-signed.sh "$OUT/install/certs/"
cp install/offline/install-offline.sh "$OUT/install-offline.sh"
cp docs/INSTALL-OFFLINE.md "$OUT/docs/"
chmod +x "$OUT/install-offline.sh" "$OUT/install/certs/"*.sh

# docker-compose.yml pentru server: fără build: (nu există cod sursă acolo)
# și pull_policy: never (nu există registry) pentru fiecare serviciu.
awk '
    /^    build:$/ { skip=2; next }
    skip > 0      { skip--; next }
    { print }
    /^    image: / { print "    pull_policy: never" }
' docker-compose.yml > "$OUT/docker-compose.yml"
grep -qE "^[[:space:]]+build:" "$OUT/docker-compose.yml" && err "docker-compose.yml offline conține încă build:"
REDIS_PASSWORD=x docker compose -f "$OUT/docker-compose.yml" --env-file "$OUT/.env.example" config -q \
    || err "docker-compose.yml offline invalid"

# Manifest
{
    echo "MeetRec — pachet de instalare offline"
    echo "Versiune:        $VERSION"
    echo "Generat:         $(date -u '+%Y-%m-%d %H:%M UTC')"
    echo "Commit:          $(git rev-parse --short HEAD 2>/dev/null || echo necunoscut)"
    echo "Platformă:       $PLATFORM"
    echo "Model Whisper:   $WHISPER_MODEL"
    echo "Diarizare:       $DIARIZATION_INCLUDED"
    echo ""
    echo "Imagini:"
    for img in "${ALL_IMAGES[@]}"; do
        printf "  %-45s %s\n" "$img" "$(docker image inspect --format '{{.Id}}' "$img" | cut -c1-19)"
    done
    echo ""
    echo "Modele ML incluse în imagini:"
    for d in services/stt-worker/models/whisper/models--* services/stt-worker/models/huggingface/hub/models--* \
             services/search-indexer/models/models--*; do
        [[ -d "$d" ]] || continue
        rev=$(cat "$d/refs/main" 2>/dev/null || echo "?")
        printf "  %-60s rev %s\n" "$(basename "$d" | sed 's/^models--//; s/--/\//')" "${rev:0:12}"
    done
    echo "  nltk punkt_tab"
    if [[ -d "$OUT/packages/docker" ]]; then
        echo ""
        echo "Docker Engine:"
        (cd "$OUT/packages/docker" && find . -type f | sort | sed 's|^\./|  |')
    fi
} > "$OUT/MANIFEST.txt"

# ── 7. Checksums + arhivă ─────────────────────────────────────
step "7/7 Checksums și arhivă"
(cd "$OUT" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
# .tar necomprimat: imaginile sunt deja .gz, recompresia doar ar consuma timp
(cd "$DIST" && tar -cf "$NAME.tar" "$NAME")
(cd "$DIST" && sha256sum "$NAME.tar" > "$NAME.tar.sha256")

ok "Pachet gata:"
echo "   $DIST/$NAME.tar  ($(du -sh "$DIST/$NAME.tar" | cut -f1))"
echo "   $DIST/$NAME.tar.sha256"
echo ""
echo "   Pe server: tar -xf $NAME.tar && cd $NAME && sudo ./install-offline.sh"
