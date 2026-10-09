FROM python:3.11-slim

LABEL service="search-indexer" \
      description="Generează embeddings semantice pentru transcrieri și expune /embed endpoint"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_HOME=/app

WORKDIR $APP_HOME

# Dependențe sistem pentru asyncpg + torch
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Model embeddings inclus în imagine (rulare offline) ───────
# Descărcat pe o mașină cu internet cu: python install/models/download-models.py
# Layout cache HuggingFace, citit de SentenceTransformer(cache_folder=/app/models).
COPY models/ /app/models/
RUN ls -d /app/models/models--sentence-transformers--* >/dev/null 2>&1 \
    || (echo "EROARE: modelul de embeddings lipsește din services/search-indexer/models/ — rulează: python install/models/download-models.py" >&2; exit 1)

ENV EMBEDDING_MODEL_PATH=/app/models \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1

COPY src/ ./src/

CMD ["python", "-m", "src.main"]
