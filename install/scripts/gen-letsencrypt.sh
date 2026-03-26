#!/usr/bin/env bash
# =============================================================
# gen-letsencrypt.sh — Obține certificate Let's Encrypt
# =============================================================
# Cerințe:
#   - Serverul trebuie să fie accesibil public pe portul 80
#   - DOMAIN trebuie să fie un nume de domeniu real (nu IP sau .local)
#   - Docker trebuie să fie instalat
#
# Folosire:
#   ./scripts/gen-letsencrypt.sh meetrec.exemplu.com email@exemplu.com
# =============================================================

set -euo pipefail

DOMAIN="${1:-}"
EMAIL="${2:-}"

if [[ -z "$DOMAIN" || -z "$EMAIL" ]]; then
    echo "Folosire: $0 <domain> <email>"
    echo "Exemplu:  $0 meetrec.companie.ro admin@companie.ro"
    exit 1
fi

SSL_DIR="$(dirname "$0")/../nginx/ssl"
mkdir -p "$SSL_DIR"

echo "→ Obțin certificate Let's Encrypt pentru: $DOMAIN"
echo "  Email notificări: $EMAIL"
echo ""

# Certbot rulează în Docker — nu necesită instalare
docker run --rm \
    -v "$(realpath "$SSL_DIR")/letsencrypt:/etc/letsencrypt" \
    -p 80:80 \
    certbot/certbot certonly \
    --standalone \
    --non-interactive \
    --agree-tos \
    --email "$EMAIL" \
    -d "$DOMAIN"

# Copiază certificatele în locul așteptat de nginx
CERT_PATH="/etc/letsencrypt/live/${DOMAIN}"
cp "$SSL_DIR/letsencrypt${CERT_PATH}/fullchain.pem" "$SSL_DIR/fullchain.pem"
cp "$SSL_DIR/letsencrypt${CERT_PATH}/privkey.pem" "$SSL_DIR/privkey.pem"
chmod 600 "$SSL_DIR/privkey.pem"
chmod 644 "$SSL_DIR/fullchain.pem"

echo ""
echo "✅ Certificate Let's Encrypt instalate cu succes!"
echo "   Valabile 90 de zile. Reînnoire: rulează din nou acest script."
echo ""
echo "ℹ️  Pentru reînnoire automată, adaugă în crontab:"
echo "   0 3 * * * $(realpath "$0") $DOMAIN $EMAIL && docker compose -f $(realpath "$(dirname "$0")/../docker-compose.yml") restart nginx"
