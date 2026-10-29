#!/usr/bin/env bash
# =============================================================
# download-extra-packages.sh — utilitare de administrare pentru serverul offline
# =============================================================
# Nu sunt necesare pentru MeetRec; ușurează administrarea unui server fără internet
# (SSH, editoare, diagnostic, backup, sincronizare oră, agenți de virtualizare).
#
# Grupuri (fiecare cu TOATE dependențele care lipsesc dintr-un sistem minimal):
#   base    — instalat mereu (dacă nu e dezactivat la instalare)
#   vmware  — open-vm-tools, doar pe VMware
#   kvm     — qemu-guest-agent, doar pe KVM/QEMU/Proxmox
#   gui     — gedit, doar pe sisteme cu interfață grafică
#
# Dependențele sunt rezolvate de apt într-un container cu aceeași versiune de sistem
# ca serverul (ubuntu:<codename> / debian:<codename>), deci necesită Docker + internet.
#
# Rezultat (în DEST, implicit dist/packages/extra):
#   <codename>/<grup>/*.deb + Packages (index de depozit apt local) + packages.txt (pachetele cerute)
#
# Folosire:
#   bash install/offline/download-extra-packages.sh [DEST] [codename ...]
# =============================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEST="${1:-$REPO_ROOT/dist/packages/extra}"
shift || true
CODENAMES=("$@")
[[ ${#CODENAMES[@]} -eq 0 ]] && CODENAMES=(jammy noble bookworm)

# postgresql-client lipsește intenționat: pg_dump din distribuție e mai vechi decât
# PostgreSQL 16 din container și refuză backup-ul — se folosește cel din container (§9.2).
# ufw lipsește intenționat: Docker ocolește regulile ufw.
BASE_PACKAGES="openssh-server nano vim curl chrony rsync htop ncdu lsof zip unzip jq \
tmux less tree bash-completion ca-certificates gnupg pv pigz xz-utils iotop sysstat \
smartmontools logrotate cron lvm2 mtr-tiny iputils-ping traceroute dnsutils net-tools \
tcpdump cifs-utils nfs-common auditd"

GROUPS_SPEC="base:$BASE_PACKAGES|vmware:open-vm-tools|kvm:qemu-guest-agent|gui:gedit"

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
    # Reîncercări: o eroare trecătoare de rețea / oglindă apt nu oprește build-ul pachetului
    for attempt in 1 2 3; do
        rm -rf "$out"
        mkdir -p "$out"
        # Fișierele ies prin stdout (tar), fără bind mount — funcționează identic pe Linux și în Git Bash.
        # apt-get download pentru pachetele cerute explicit: cele prezente deja în imaginea de bază
        # nu sunt descărcate de --download-only, dar pot lipsi de pe server.
        docker run --rm --platform linux/amd64 -e GROUPS_SPEC="$GROUPS_SPEC" "$image" sh -c "
            set -e
            export DEBIAN_FRONTEND=noninteractive
            apt-get update -qq >/dev/null
            IFS='|'
            for spec in \$GROUPS_SPEC; do
                group=\${spec%%:*}; pkgs=\${spec#*:}
                mkdir -p /debs/\$group/partial
                IFS=' '
                apt-get install -y -qq --download-only --no-install-recommends \
                    -o Dir::Cache::Archives=/debs/\$group/ \$pkgs >/dev/null
                (cd /debs/\$group && apt-get download -qq \$pkgs >/dev/null)
                rm -rf /debs/\$group/partial /debs/\$group/lock
                echo \$pkgs | tr ' ' '\n' > /debs/\$group/packages.txt   # pachetele cerute, pentru installer
                IFS='|'
            done
            # Index apt (Packages): pe server fiecare grup devine un depozit local, iar apt
            # rezolvă singur dependențele, versiunile și conflictele (ex. chrony ↔ systemd-timesyncd)
            apt-get install -y -qq --no-install-recommends dpkg-dev >/dev/null 2>&1
            for d in /debs/*/; do (cd \$d && dpkg-scanpackages --multiversion . /dev/null > Packages 2>/dev/null); done
            tar -cf - -C /debs .
        " | tar -xf - -C "$out" && break
        [[ $attempt -lt 3 ]] || { echo "  ❌ descărcarea a eșuat de 3 ori pentru $codename" >&2; exit 1; }
        echo "  ↻ eroare la descărcare, reîncerc ($attempt/3)..."
        sleep 10
    done
    for group in base vmware kvm gui; do
        count=$(ls "$out/$group"/*.deb 2>/dev/null | wc -l)
        [[ $count -gt 0 ]] || { echo "  ❌ niciun pachet descărcat pentru $codename/$group" >&2; exit 1; }
        echo "  ✓ $group: $count pachete ($(du -sh "$out/$group" | cut -f1))"
    done
done

echo "✅ Utilitare de administrare descărcate în $DEST"
