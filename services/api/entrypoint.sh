#!/bin/sh
# entrypoint.sh — Startup script pentru API
export PYTHONPATH=/app

# ============================================================
# STRATEGIE MIGRĂRI:
# 1. Postgres pornit → schema inițializată cu init.sql (completă, la zi)
# 2. Alembic verifică dacă tabelul alembic_version există
#    - NU: stamp head (schema aplicată de init.sql, marcăm ca la zi)
#    - DA: upgrade head (deployment existent, aplică migrări noi)
# 3. Pornește uvicorn
#
# RETRY LOGIC: dacă psql fail-uiește, reîncercă până service e healthy
# ============================================================

set -e

echo "[entrypoint] Waiting for database to be fully ready..."

# ── Retry logic pentru conexiune la DB ─────────────────────
# psql poate pica dacă schema e încă în inițializare
MAX_RETRIES=30
RETRY_DELAY=2
RETRY_COUNT=0

# Convertim DATABASE_URL pentru psql (asyncpg → sync protocol)
# SAFER: nu folosim sed, ci `python` pentru a fi siguri cu special chars
SYNC_DB_URL=$(python3 << 'PYTHON_EOF'
import os
db_url = os.environ.get('DATABASE_URL', '')
# Înlocuiește postgresql+asyncpg cu postgresql
sync_url = db_url.replace('postgresql+asyncpg://', 'postgresql://')
print(sync_url)
PYTHON_EOF
)

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
  if psql "$SYNC_DB_URL" -tAc "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='alembic_version')" 2>/dev/null; then
    TABLE_EXISTS="t"
    break
  fi
  RETRY_COUNT=$((RETRY_COUNT + 1))
  if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then
    echo "[entrypoint] Database not ready yet, retrying in ${RETRY_DELAY}s ($RETRY_COUNT/$MAX_RETRIES)..."
    sleep $RETRY_DELAY
  fi
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
  echo "[entrypoint] ERROR: Database connection failed after $MAX_RETRIES retries"
  exit 1
fi

echo "[entrypoint] Database connection established"
echo "[entrypoint] Checking migration state..."

# ── Verific migration status ────────────────────────────────
TABLE_EXISTS=$(psql "$SYNC_DB_URL" -tAc \
  "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='alembic_version')" \
  2>/dev/null || echo "f")

# Verificăm că tabelele critice din init.sql există (detectează schema incompletă)
USERS_EXISTS=$(psql "$SYNC_DB_URL" -tAc \
  "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='users')" \
  2>/dev/null || echo "f")

if [ "$USERS_EXISTS" = "f" ]; then
  echo "[entrypoint] ERROR: 'users' table missing — init.sql failed to complete."
  echo "[entrypoint] Fix: run 'docker compose down -v && docker compose up' to reinitialize."
  exit 1
fi

if [ "$TABLE_EXISTS" = "f" ]; then
  echo "[entrypoint] alembic_version missing — stamping head (schema applied via init.sql)"
  alembic stamp head
else
  echo "[entrypoint] alembic_version found — running upgrade head (apply pending migrations)"
  alembic upgrade head
fi

echo "[entrypoint] Migrations complete. Starting uvicorn..."
exec uvicorn src.main:app --host 0.0.0.0 --port 8080
