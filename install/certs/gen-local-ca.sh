#!/usr/bin/env bash
# =============================================================
# gen-local-ca.sh — CA locală + certificat server pentru nginx
# =============================================================
# Recomandat pentru rețele izolate (offline) / intranet:
#   - se creează O SINGURĂ DATĂ o autoritate de certificare (CA) locală
#   - certificatul serverului e semnat de această CA
#   - pe fiecare calculator client se importă O SINGURĂ DATĂ meetrec-ca.crt
#     → browserul nu mai afișează avertismente, nici după reînnoirea certificatului
#
# Folosire:
#   bash install/certs/gen-local-ca.sh meetrec.firma.local
#   bash install/certs/gen-local-ca.sh 192.168.10.5
#   bash install/certs/gen-local-ca.sh meetrec.firma.local 192.168.10.5   # mai multe nume/IP-uri
#
# Fișiere (în nginx/ssl/):
#   fullchain.pem, privkey.pem    → folosite de nginx
#   meetrec-ca.crt                → DISTRIBUIE la clienți (public)
#   ca/meetrec-ca.key             → cheia CA — PĂSTREAZĂ SECRETĂ (backup offline)
#
# Rerulare: CA-ul existent e refolosit; se reemite doar certificatul serverului.
# Dacă ai deja o CA a organizației, NU folosi acest script — cere un certificat
# de la CA-ul organizației și copiază-l ca nginx/ssl/fullchain.pem + privkey.pem.
# =============================================================

set -euo pipefail

if [[ $# -eq 0 ]]; then
    set -- "$(hostname -f 2>/dev/null || hostname)"
fi

SSL_DIR="$(cd "$(dirname "$0")/../.." && pwd)/nginx/ssl"
CA_DIR="$SSL_DIR/ca"
CA_KEY="$CA_DIR/meetrec-ca.key"
CA_CRT="$SSL_DIR/meetrec-ca.crt"
SERVER_KEY="$SSL_DIR/privkey.pem"
SERVER_CRT="$SSL_DIR/fullchain.pem"

mkdir -p "$CA_DIR"
chmod 700 "$CA_DIR"

# ── SAN: toate numele și IP-urile primite + localhost ─────────
SAN="DNS:localhost,IP:127.0.0.1"
for name in "$@"; do
    if [[ "$name" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        SAN="IP:${name},${SAN}"
    else
        SAN="DNS:${name},${SAN}"
    fi
done
PRIMARY="$1"

# ── 1. CA (o singură dată, 10 ani) ────────────────────────────
if [[ -f "$CA_KEY" && -f "$CA_CRT" ]]; then
    echo "→ Refolosesc CA-ul existent: $CA_CRT"
else
    echo "→ Generez CA locală MeetRec (10 ani)"
    openssl req -x509 -new -nodes -newkey rsa:4096 -sha256 -days 3650 \
        -keyout "$CA_KEY" -out "$CA_CRT" \
        -subj "/C=RO/O=MeetRec/CN=MeetRec Local CA" \
        -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
        -addext "keyUsage=critical,keyCertSign,cRLSign" \
        2>/dev/null
    chmod 600 "$CA_KEY"
    chmod 644 "$CA_CRT"
fi

# ── 2. Certificat server (825 zile — limita acceptată de macOS/iOS) ──
echo "→ Emit certificat server pentru: $SAN"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

openssl req -new -nodes -newkey rsa:2048 -sha256 \
    -keyout "$TMP/server.key" -out "$TMP/server.csr" \
    -subj "/C=RO/O=MeetRec/CN=${PRIMARY}" 2>/dev/null

cat > "$TMP/ext.cnf" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=${SAN}
EOF

openssl x509 -req -sha256 -days 825 \
    -in "$TMP/server.csr" -CA "$CA_CRT" -CAkey "$CA_KEY" -CAcreateserial \
    -CAserial "$CA_DIR/meetrec-ca.srl" \
    -extfile "$TMP/ext.cnf" -out "$TMP/server.crt" 2>/dev/null

# fullchain = certificat server + CA (nginx trimite lanțul complet)
cat "$TMP/server.crt" "$CA_CRT" > "$SERVER_CRT"
install -m 600 "$TMP/server.key" "$SERVER_KEY"
chmod 644 "$SERVER_CRT"

echo ""
echo "✅ Certificate generate:"
echo "   nginx:   $SERVER_CRT + $SERVER_KEY (valabil 825 zile)"
echo "   CA:      $CA_CRT  ← importă acest fișier pe calculatoarele client"
echo "   Cheie CA: $CA_KEY  ← păstreaz-o secretă (backup offline)"
echo ""
echo "   Import pe clienți: vezi docs/INSTALL-OFFLINE.md, secțiunea „Certificate HTTPS”."
