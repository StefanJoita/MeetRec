# services/stt-worker/Dockerfile
# ============================================================
# Imagine Docker pentru STT Worker
# ============================================================
# Single-stage (nu multi-stage ca la API):
#   - PyTorch + Whisper sunt deja ~800MB instalate
#   - Separarea în builder/runtime economisește ~100MB dar
#     adaugă complexitate nejustificată pentru un MVP
#   - Multi-stage devine relevant la producție pentru securitate
#
# DIMENSIUNEA IMAGINII FINALE: ~6-7 GB (cu large-v3)
#   - python:3.11-slim:          ~130 MB
#   - ffmpeg:                    ~400 MB
#   - torch CPU + whisperx dep:  ~1.5 GB
#   - modele (large-v3, wav2vec2 ro, pyannote, nltk): ~4.5 GB
#
# PREREQUISIT: python install/models/download-models.py (populează models/)
# PRIMA BUILD durează 15-30 minute (download PyTorch).
# Rebuild-urile ulterioare durează <1 minut (Docker cache).
#
# Docker layer caching — de ce copiem requirements.txt ÎNAINTE de src/?
#   Layer 1: COPY requirements.txt + pip install (cache dacă req nu se schimbă)
#   Layer 2: COPY src/                            (rebuild la orice modificare cod)
#   → Modificarea unui fișier .py nu re-instalează PyTorch (durează 20 min!)
# ============================================================

FROM python:3.11-slim

LABEL service="stt-worker" \
      description="Transcriere audio offline cu WhisperX + diarizare vorbitori"

# Variabile de mediu Python:
# PYTHONDONTWRITEBYTECODE: nu crea fișiere .pyc (economisim spațiu în container)
# PYTHONUNBUFFERED: output fără buffering (logurile apar imediat în docker logs)
# HF_HOME: directorul cache HuggingFace (modelele sunt copiate aici la build)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/app/models/huggingface

WORKDIR /app

# ── Dependențe de sistem ──────────────────────────────────────
# ffmpeg este OBLIGATORIU — Whisper îl folosește pentru:
#   - Decodarea fișierelor MP3, M4A, OGG, FLAC (nu doar WAV)
#   - Resampling la 16kHz mono (formatul intern al Whisper)
# Fără ffmpeg: "FileNotFoundError: [Errno 2] No such file or directory: 'ffmpeg'"
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# ── Instalare dependențe Python ───────────────────────────────
# STRATEGIE CPU-only:
#   --index-url https://download.pytorch.org/whl/cpu  → index PRIMAR (doar CPU builds)
#   --extra-index-url https://pypi.org/simple          → fallback pentru restul pachetelor
#
# De ce funcționează:
#   CDN-ul PyTorch de la /cpu conține EXCLUSIV torch+cpu, torchaudio+cpu etc.
#   Când pip caută torch, îl găsește aici (CPU) înainte să ajungă la PyPI (CUDA).
#   Pachetele care nu sunt pe CDN (whisperx, asyncpg etc.) vin din PyPI ca fallback.
COPY requirements.txt .
RUN pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    --extra-index-url https://pypi.org/simple \
    -r requirements.txt

# ── User non-root ─────────────────────────────────────────────
# Creat ÎNAINTE de COPY: folosim COPY --chown în loc de `chown -R` ulterior,
# care ar duplica gigaocteții de modele într-un layer nou.
RUN useradd -m -u 1000 appuser \
    && mkdir -p /data/processed \
    && chown appuser:appuser /app /data/processed

# ── Modele ML incluse în imagine (rulare offline) ─────────────
# Descărcate pe o mașină cu internet cu: python install/models/download-models.py
#   models/whisper/       → faster-whisper (CTranslate2), cache HF (download_root)
#   models/huggingface/   → $HF_HOME: wav2vec2 aliniere + pyannote diarizare
#   models/nltk_data/     → punkt_tab (whisperx/alignment.py)
# La runtime nu se face NICIO cerere de rețea (HF_HUB_OFFLINE=1).
#
# models/whisper/ poate conține mai multe modele (ex. small pentru dev și
# large-v3 pentru pachetul offline); în imagine intră DOAR WHISPER_MODEL
# (build arg din docker-compose.yml), ca imaginea să nu crească inutil.
ARG WHISPER_MODEL=large-v3
LABEL meetrec.whisper_model="${WHISPER_MODEL}"
RUN --mount=type=bind,source=models,target=/tmp/models \
    set -e; \
    case "$WHISPER_MODEL" in large) repo=large-v3 ;; *) repo="$WHISPER_MODEL" ;; esac; \
    src=$(ls -d /tmp/models/whisper/models--*--faster-whisper-"$repo" 2>/dev/null | head -1); \
    if [ -z "$src" ]; then \
        echo "EROARE: lipsește modelul Whisper '$WHISPER_MODEL' (models/whisper/models--*--faster-whisper-$repo) — rulează: python install/models/download-models.py --whisper-model $WHISPER_MODEL" >&2; \
        exit 1; \
    fi; \
    mkdir -p /app/models/whisper; \
    cp -a "$src" /app/models/whisper/; \
    for d in huggingface nltk_data; do \
        if [ -d "/tmp/models/$d" ]; then cp -a "/tmp/models/$d" /app/models/; fi; \
    done; \
    chown -R appuser:appuser /app/models
RUN set -e; \
    for required in \
        "/app/models/huggingface/hub/models--gigant--romanian-wav2vec2" \
        "/app/models/nltk_data/tokenizers/punkt_tab"; do \
        if ! ls -d $required >/dev/null 2>&1; then \
            echo "EROARE: lipsește $required — rulează: python install/models/download-models.py" >&2; \
            exit 1; \
        fi; \
    done; \
    ls -d /app/models/huggingface/hub/models--pyannote--* >/dev/null 2>&1 \
        || echo "ATENȚIE: modelul pyannote lipsește — diarizarea nu va funcționa offline."

ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    NLTK_DATA=/app/models/nltk_data

# ── Copiem codul sursă ────────────────────────────────────────
COPY --chown=appuser:appuser src/ ./src/

# ── Rulăm ca non-root ─────────────────────────────────────────
# Securitate: procesele din container nu ar trebui să fie root
# (dacă aplicația e compromisă, atacatorul nu e root pe host)
USER appuser

# ── Comandă de start ──────────────────────────────────────────
# python -m src.main = rulează src/main.py ca modul Python
# (mai robust decât `python src/main.py` — setează corect PYTHONPATH)
CMD ["python", "-m", "src.main"]
