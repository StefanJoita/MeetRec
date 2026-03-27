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
# DIMENSIUNEA IMAGINII FINALE: ~4-5 GB
#   - python:3.11-slim:  ~130 MB
#   - ffmpeg:            ~100 MB
#   - torch CPU-only:    ~800 MB
#   - openai-whisper:    ~50 MB
#   - restul dep:        ~200 MB
#   - TOTAL:             ~1.3 GB imagine
#
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
# HF_HOME: directorul unde HuggingFace stochează modelele descărcate
# HF_HUB_OFFLINE: setat la runtime pentru a preveni verificări online
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

# ── Directoare pentru volume ──────────────────────────────────
# Modelele sunt descărcate la primul start și stocate în volume Docker persistente.
# Rebuild-ul imaginii durează <5 minute (nu mai bake-uim 3+ GB de modele).
# /data/processed:          audio files (montat :rw)
# /app/models/whisper:      model Whisper (~1.5-3 GB, descarcat la primul start)
# /app/models/huggingface:  modele pyannote/wav2vec2 (~500 MB, descarcat la primul start)
RUN mkdir -p /data/processed /app/models/whisper /app/models/huggingface

# ── Copiem codul sursă ────────────────────────────────────────
COPY src/ ./src/

# ── Rulăm ca non-root ─────────────────────────────────────────
# Securitate: procesele din container nu ar trebui să fie root
# (dacă aplicația e compromisă, atacatorul nu e root pe host)
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# ── Comandă de start ──────────────────────────────────────────
# python -m src.main = rulează src/main.py ca modul Python
# (mai robust decât `python src/main.py` — setează corect PYTHONPATH)
CMD ["python", "-m", "src.main"]
