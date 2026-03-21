#!/bin/sh
# entrypoint.sh — Startup script pentru API
export PYTHONPATH=/app
# Aplică migrările Alembic, apoi pornește uvicorn.
#
# Logică:
#   - Dacă alembic_version nu există → schema a fost creată manual
#     → stamp head (marchează toate migrările ca aplicate fără să le ruleze)
#   - Dacă alembic_version există → rulează upgrade head (aplică migrările lipsă)

set -e

echo "[entrypoint] Checking migration state..."

# Verificăm dacă tabelul alembic_version există în DB
# Dacă nu există, schema a fost creată manual → stamp head
DB_CLEAN_URL=$(echo "$DATABASE_URL" | sed 's/postgresql+asyncpg/postgresql/')

TABLE_EXISTS=$(psql "$DB_CLEAN_URL" -tAc \
  "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='alembic_version')" \
  2>/dev/null || echo "f")

if [ "$TABLE_EXISTS" = "f" ]; then
  echo "[entrypoint] alembic_version missing — stamping head (schema already applied manually)"
  alembic stamp head
else
  echo "[entrypoint] alembic_version found — running upgrade head"
  alembic upgrade head
fi

echo "[entrypoint] Starting uvicorn..."
exec uvicorn src.main:app --host 0.0.0.0 --port 8080
