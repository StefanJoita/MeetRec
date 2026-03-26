#!/usr/bin/env bash
# =============================================================
# gen-self-signed.sh — Generează certificate SSL self-signed
# =============================================================
# Folosire:
#   ./scripts/gen-self-signed.sh                    → CN=localhost
#   ./scripts/gen-self-signed.sh meetrec.local      → CN=meetrec.local
#   ./scripts/gen-self-signed.sh 192.168.1.100      → CN=IP
#
# Certificate generate: nginx/ssl/fullchain.pem + privkey.pem
# Valabile 10 ani (3650 zile)
# =============================================================

set -euo pipefail

DOMAIN="${1:-localhost}"
SSL_DIR="$(dirname "$0")/../nginx/ssl"
CERT="$SSL_DIR/fullchain.pem"
KEY="$SSL_DIR/privkey.pem"

mkdir -p "$SSL_DIR"

# Determină dacă DOMAIN e IP sau hostname
if [[ "$DOMAIN" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    SAN="IP:${DOMAIN},IP:127.0.0.1"
else
    SAN="DNS:${DOMAIN},DNS:localhost,IP:127.0.0.1"
fi

echo "→ Generez certificate SSL self-signed pentru: $DOMAIN"
echo "  SAN: $SAN"
echo "  Output: $CERT / $KEY"
echo ""

openssl req -x509 -nodes -days 3650 \
    -newkey rsa:2048 \
    -keyout "$KEY" \
    -out "$CERT" \
    -subj "/C=RO/ST=Romania/L=Bucharest/O=MeetRec/CN=${DOMAIN}" \
    -addext "subjectAltName=${SAN}" \
    2>/dev/null

chmod 600 "$KEY"
chmod 644 "$CERT"

echo "✅ Certificate generate cu succes!"
echo ""
echo "  Certificate: $CERT"
echo "  Cheie privată: $KEY"
echo "  Valabile: 10 ani"
echo ""
echo "⚠️  Browserul va afișa un avertisment de securitate (self-signed)."
echo "   Poți adăuga certificatul la trusted store-ul sistemului pentru a-l elimina."
echo "   Pe Chrome/Edge: click 'Advanced' → 'Proceed to <host>'"
