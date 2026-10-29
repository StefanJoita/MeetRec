#!/usr/bin/env bash
# =============================================================
# restore-backup.sh — restaurează MeetRec din backup-ul zilnic
# =============================================================
# Rulat din directorul pachetului (cel cu .env și docker-compose.yml), ca root:
#   sudo ./restore-backup.sh                       # cel mai nou backup al bazei de date
#   sudo ./restore-backup.sh --list                # backup-urile disponibile
#   sudo ./restore-backup.sh --db meetrec-20261029-020000.dump
#   sudo ./restore-backup.sh --no-audio            # doar baza de date
#
# Pași:
#   1. Oprește serviciile aplicației (rămân postgres și redis)
#   2. Recreează baza de date din dump (pg_dump -Fc), cu pg_restore din imaginea
#      audit-retention (aceeași versiune ca pg_dump care a făcut backup-ul)
#   3. Copiază în volumul audio fișierele din backup care lipsesc (nu șterge nimic)
#   4. Pornește serviciile; migrațiile rulează automat dacă backup-ul e de la o versiune mai veche
#
# Configurația (.env, certificate) NU se suprascrie: arhiva din config/ se dezarhivează
# cu --config într-un folder separat, pentru comparare (docs/INSTALL-OFFLINE.md §9.3).
# Backup-ul se face din BACKUP_HOST_PATH (.env); pe alt server, copiază întâi folderul.
# =============================================================

set -euo pipefail

BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BUNDLE_DIR"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✅ $*${NC}"; }
info() { echo -e "${BLUE}ℹ️  $*${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $*${NC}"; }
err()  { echo -e "${RED}❌ $*${NC}" >&2; exit 1; }

env_get() { grep "^$1=" .env | tail -1 | cut -d= -f2- | sed 's/[[:space:]]*#.*//' | tr -d '"'; }

DB_FILE="" AUDIO=true CONFIG=false LIST=false YES=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --db)       DB_FILE="${2:-}"; shift ;;
        --no-audio) AUDIO=false ;;
        --config)   CONFIG=true ;;
        --list)     LIST=true ;;
        --yes)      YES=true ;;
        *) err "Opțiune necunoscută: $1 (vezi antetul scriptului)" ;;
    esac
    shift
done

[[ $EUID -eq 0 ]] || err "Rulează ca root: sudo ./restore-backup.sh"
[[ -f .env && -f docker-compose.yml ]] || err "Rulează scriptul din directorul instalării (cu .env și docker-compose.yml)."

BACKUP_DIR=$(env_get BACKUP_HOST_PATH)
[[ "$BACKUP_DIR" == ./* ]] && BACKUP_DIR="$BUNDLE_DIR/${BACKUP_DIR#./}"
[[ -d "$BACKUP_DIR/db" ]] || err "Nu găsesc backup-uri în $BACKUP_DIR/db (BACKUP_HOST_PATH din .env)."

if [[ "$LIST" == true ]]; then
    echo "Baza de date ($BACKUP_DIR/db):"
    ls -lh "$BACKUP_DIR/db" | awk 'NR>1 {print "  " $9 "  " $5}'
    echo "Fișiere audio în backup: $(find "$BACKUP_DIR/audio" -type f 2>/dev/null | wc -l)"
    echo "Fișiere audio șterse din aplicație, păstrate: $(find "$BACKUP_DIR/audio-deleted" -type f 2>/dev/null | wc -l)"
    exit 0
fi

[[ -n "$DB_FILE" ]] || DB_FILE=$(ls "$BACKUP_DIR/db" | grep -E '^meetrec-[0-9]{8}-[0-9]{6}\.dump$' | sort | tail -1)
[[ -n "$DB_FILE" && -f "$BACKUP_DIR/db/$DB_FILE" ]] || err "Nu există backup-ul bazei de date: $DB_FILE"

DB_USER=$(env_get POSTGRES_USER)
DB_NAME=$(env_get POSTGRES_DB)

echo -e "${BOLD}\n  Restaurare MeetRec din backup\n${NC}"
echo "  Baza de date: $BACKUP_DIR/db/$DB_FILE ($(du -h "$BACKUP_DIR/db/$DB_FILE" | cut -f1))"
echo "  Audio:        $([[ "$AUDIO" == true ]] && echo "fișierele din $BACKUP_DIR/audio care lipsesc" || echo "nu")"
echo ""
warn "Baza de date curentă ($DB_NAME) va fi ÎNLOCUITĂ. Tot ce s-a adăugat după acest backup se pierde."
if [[ "$YES" != true ]]; then
    read -rp "  Scrie „da” pentru a continua: " answer
    [[ "$answer" == "da" ]] || err "Anulat."
fi

info "Opresc serviciile aplicației..."
docker compose stop nginx frontend api ingest stt-worker search-indexer audit-retention >/dev/null
docker compose up -d postgres redis >/dev/null
for _ in $(seq 1 30); do
    docker compose exec -T postgres pg_isready -U "$DB_USER" >/dev/null 2>&1 && break
    sleep 2
done

info "Recreez baza de date $DB_NAME..."
docker compose exec -T postgres psql -U "$DB_USER" -d postgres -v ON_ERROR_STOP=1 -q \
    -c "DROP DATABASE IF EXISTS \"$DB_NAME\" WITH (FORCE)" \
    -c "CREATE DATABASE \"$DB_NAME\" OWNER \"$DB_USER\"" \
    || err "Nu am putut recrea baza de date."

info "Restaurez $DB_FILE..."
docker compose run --rm --no-deps -T --entrypoint sh -e DUMP="$DB_FILE" audit-retention -c \
    'pg_restore --exit-on-error --no-owner --dbname="$(echo "$DATABASE_URL" | sed "s|+asyncpg||")" "/backups/db/$DUMP"' \
    || err "pg_restore a eșuat. Serviciile sunt oprite; repornește-le după remediere cu: docker compose up -d"
ok "Baza de date restaurată"

if [[ "$AUDIO" == true ]]; then
    info "Copiez fișierele audio care lipsesc..."
    docker compose run --rm --no-deps -T --entrypoint sh audit-retention -c \
        'cp -an /backups/audio/. /data/processed/ && find /data/processed -type f | wc -l' \
        | tail -1 | xargs -I{} echo "  {} fișiere audio în volum"
    ok "Fișiere audio restaurate"
fi

if [[ "$CONFIG" == true ]]; then
    CFG=$(ls "$BACKUP_DIR/config" 2>/dev/null | sort | tail -1)
    if [[ -n "$CFG" ]]; then
        OUT="$BUNDLE_DIR/restored-config-$(date +%Y%m%d-%H%M%S)"
        mkdir -p "$OUT" && chmod 700 "$OUT"
        tar -xzf "$BACKUP_DIR/config/$CFG" -C "$OUT"
        ok "Configurația din $CFG e în $OUT (compar-o cu .env și nginx/ssl; nu am suprascris nimic)"
    else
        warn "Nu există arhive de configurație în $BACKUP_DIR/config."
    fi
fi

info "Pornesc serviciile..."
docker compose up -d --no-build --pull never >/dev/null
docker compose restart nginx >/dev/null
ok "Restaurare terminată. Verifică aplicația și Administrare → Stare sistem."
