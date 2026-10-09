#!/usr/bin/env bash
# =============================================================
# download-system-packages.sh — pachetele de sistem de care au nevoie
# Docker Engine și installerul pe serverul offline (Ubuntu/Debian)
# =============================================================
# Pachete: iptables, nftables (rețelistica Docker), openssl (certificate HTTPS),
# libseccomp2 — împreună cu TOATE dependențele lor care lipsesc dintr-un sistem minimal.
#
# Dependențele sunt rezolvate de apt într-un container cu aceeași versiune de sistem
# ca serverul (ubuntu:<codename> / debian:<codename>), deci necesită Docker + internet.
# Pe server, install-offline.sh instalează doar pachetele care lipsesc.
#
# Rezultat (în DEST, implicit dist/packages/system):
#   <codename>/*.deb
#
# Folosire:
#   bash install/offline/download-system-packages.sh [DEST] [codename ...]
#   ex: bash install/offline/download-system-packages.sh dist/packages/system jammy noble
#       bash install/offline/download-system-packages.sh deps focal     # alt sistem (Ubuntu 20.04)
# =============================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEST="${1:-$REPO_ROOT/dist/packages/system}"
shift || true
CODENAMES=("$@")
[[ ${#CODENAMES[@]} -eq 0 ]] && CODENAMES=(jammy noble bookworm)

PACKAGES="iptables nftables openssl"
# Prezente în imaginea de bază (deci apt nu le descarcă), dar necesare pe server
ALWAYS_DOWNLOAD="libseccomp2"

# Imaginea Docker oficială are tag-uri după codename (ubuntu:jammy, debian:bookworm, ...)
image_of() {
    case "$1" in
        buster|bullseye|bookworm|trixie) echo "debian:$1" ;;
        *) echo "ubuntu:$1" ;;
    esac
}

for codename in "${CODENAMES[@]}"; do
    image=$(image_of "$codename")
    out="$DEST/$codename"
    echo "→ $codename ($image)"
    rm -rf "$out"
    mkdir -p "$out"
    # Fișierele ies prin stdout (tar), fără bind mount — funcționează identic pe Linux și în Git Bash
    docker run --rm --platform linux/amd64 "$image" sh -c "
        set -e
        export DEBIAN_FRONTEND=noninteractive
        mkdir -p /debs/partial
        apt-get update -qq >/dev/null
        apt-get install -y -qq --download-only --no-install-recommends \
            -o Dir::Cache::Archives=/debs/ $PACKAGES >/dev/null
        cd /debs && apt-get download -qq $ALWAYS_DOWNLOAD >/dev/null
        tar -cf - -C /debs \$(cd /debs && ls *.deb)
    " | tar -xf - -C "$out"
    count=$(ls "$out"/*.deb 2>/dev/null | wc -l)
    [[ $count -gt 0 ]] || { echo "  ❌ niciun pachet descărcat pentru $codename" >&2; exit 1; }
    echo "  ✓ $count pachete ($(du -sh "$out" | cut -f1))"
done

echo "✅ Pachete de sistem descărcate în $DEST"
