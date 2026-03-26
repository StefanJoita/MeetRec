# services/api/Dockerfile
# ============================================================
# Multi-stage build pentru imaginea API
# ============================================================
# Stage 1 (builder): instalăm dependențele
# Stage 2 (runtime): copiem doar ce e necesar → imagine mai mică
#
# De ce multi-stage?
# - Imaginea finală nu conține compilatoare, pip cache, etc.
# - Rezultat: ~200MB în loc de ~600MB
# ============================================================

# ── Stage 1: Builder ─────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Instalăm dependențele de build
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copiem requirements și instalăm într-un director separat
# (nu în sistem, pentru a putea fi copiate în stage 2)
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: Runtime ─────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Dependențe runtime (libpq pentru asyncpg, postgresql-client pentru psql în entrypoint)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copiem pachetele instalate din stage 1
COPY --from=builder /install /usr/local

# Copiem codul sursă + configurare Alembic + entrypoint
COPY src/ ./src/
COPY tests/ ./tests/
COPY alembic/ ./alembic/
COPY alembic.ini ./alembic.ini
COPY entrypoint.sh ./entrypoint.sh

# User non-root pentru securitate
# chmod +x și chown se fac înainte de USER appuser (altfel permission denied)
RUN chmod +x ./entrypoint.sh \
    && useradd -m -u 1000 appuser \
    && chown -R appuser:appuser /app \
    && mkdir -p /data/processed /data/exports \
    && chown -R appuser:appuser /data
USER appuser

# Portul pe care ascultă API-ul
EXPOSE 8080

# Health check intern (Docker verifică periodic)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Script de startup: verifică starea Alembic, aplică migrările, pornește uvicorn
CMD ["./entrypoint.sh"]
