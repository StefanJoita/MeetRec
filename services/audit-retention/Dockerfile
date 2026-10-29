# bookworm: postgresql-client 15, aceeași versiune ca serverul (pgvector/pgvector:pg15).
# Un pg_dump mai nou produce dump-uri pe care PostgreSQL 15 nu le poate restaura.
FROM python:3.11-slim-bookworm

LABEL service="audit-retention" \
      description="Retenție, curățenie și backup zilnic (bază de date, audio, configurație)"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_HOME=/app

WORKDIR $APP_HOME

# Dependențe sistem pentru asyncpg (compilare C extensions);
# postgresql-client: pg_dump / pg_restore pentru backup (src/backup.py, restore-backup.sh)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

CMD ["python", "-m", "src.main"]
