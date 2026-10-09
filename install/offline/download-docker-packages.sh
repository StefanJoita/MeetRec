#!/usr/bin/env bash
# =============================================================
# download-docker-packages.sh — descarcă Docker Engine + Compose
# pentru instalare pe un server Linux FĂRĂ internet.
# =============================================================
# Sursa: depozitul oficial https://download.docker.com (amd64)
#
# Rezultat (în DEST, implicit dist/packages/docker):
#   deb/<codename>/*.deb   — pentru Ubuntu 22.04 (jammy), 24.04 (noble), Debian 12 (bookworm)
#                            docker-ce, docker-ce-cli, containerd.io,
#                            docker-buildx-plugin, docker-compose-plugin
#   static/docker-<ver>.tgz             — binare statice (orice distribuție, fallback)
#   static/docker-compose-linux-x86_64  — plugin Compose v2 (fallback)
#
# Folosire:
#   bash install/offline/download-docker-packages.sh [DEST] [codename ...]
#   ex: bash install/offline/download-docker-packages.sh dist/packages/docker jammy noble
# Necesită: bash, curl, awk, sort -V
# =============================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEST="${1:-$REPO_ROOT/dist/packages/docker}"
shift || true
CODENAMES=("$@")
[[ ${#CODENAMES[@]} -eq 0 ]] && CODENAMES=(jammy noble bookworm)

ARCH=amd64
BASE=https://download.docker.com/linux
PACKAGES=(containerd.io docker-ce-cli docker-ce docker-buildx-plugin docker-compose-plugin)

distro_of() {
    case "$1" in
        bookworm|bullseye|trixie) echo debian ;;
        *) echo ubuntu ;;
    esac
}

# Din indexul "Packages" alege cea mai nouă versiune a unui pachet → afișează "Filename"
latest_filename() {
    local index="$1" pkg="$2"
    awk -v pkg="$pkg" '
        /^Package: /  { name=$2 }
        /^Version: /  { ver=$2 }
        /^Filename: / { if (name == pkg) print ver "\t" $2 }
    ' "$index" | sort -V -k1,1 | tail -1 | cut -f2
}

mkdir -p "$DEST"

for codename in "${CODENAMES[@]}"; do
    distro=$(distro_of "$codename")
    out="$DEST/deb/$codename"
    mkdir -p "$out"
    index="$out/.Packages"
    echo "→ $distro/$codename ($ARCH)"
    curl -fsSL "$BASE/$distro/dists/$codename/stable/binary-$ARCH/Packages" -o "$index"
    for pkg in "${PACKAGES[@]}"; do
        file=$(latest_filename "$index" "$pkg")
        [[ -n "$file" ]] || { echo "  ❌ $pkg negăsit în index" >&2; exit 1; }
        name=$(basename "$file")
        if [[ -f "$out/$name" ]]; then
            echo "  ✓ $name (exista)"
        else
            curl -fsSL "$BASE/$distro/$file" -o "$out/$name.part" && mv "$out/$name.part" "$out/$name"
            echo "  ✓ $name"
        fi
    done
    rm -f "$index"
done

# ── Binare statice (fallback pentru alte distribuții) ─────────
static="$DEST/static"
mkdir -p "$static"
echo "→ binare statice"
latest_static=$(curl -fsSL "$BASE/static/stable/x86_64/" \
    | grep -oE 'docker-[0-9]+\.[0-9]+\.[0-9]+\.tgz' | sort -uV | tail -1)
if [[ ! -f "$static/$latest_static" ]]; then
    curl -fsSL "$BASE/static/stable/x86_64/$latest_static" -o "$static/$latest_static.part" \
        && mv "$static/$latest_static.part" "$static/$latest_static"
fi
echo "  ✓ $latest_static"

compose_ver=$(curl -fsSLI -o /dev/null -w '%{url_effective}' https://github.com/docker/compose/releases/latest | sed 's|.*/tag/||')
if [[ ! -f "$static/docker-compose-linux-x86_64" ]]; then
    curl -fsSL "https://github.com/docker/compose/releases/download/$compose_ver/docker-compose-linux-x86_64" \
        -o "$static/docker-compose-linux-x86_64.part" && mv "$static/docker-compose-linux-x86_64.part" "$static/docker-compose-linux-x86_64"
fi
echo "  ✓ docker-compose $compose_ver"

echo "✅ Pachete Docker descărcate în $DEST"
