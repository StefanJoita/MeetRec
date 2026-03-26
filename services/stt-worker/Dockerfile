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

# ── Build args ────────────────────────────────────────────────
# HF_TOKEN: token HuggingFace pentru descărcarea modelului pyannote
#   - necesar DOAR la build time (model baked în imagine)
#   - la runtime nu e nevoie de internet sau token
#   - dacă nu e setat, diarizarea nu va fi disponibilă
# WHISPER_MODEL: modelul Whisper de pre-descărcat în imagine
ARG HF_TOKEN=""
ARG WHISPER_MODEL="medium"

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
# /data/processed:          va fi montat ca volum read-only (audio files)
# /app/models/whisper:      modele Whisper descărcate la build
# /app/models/huggingface:  modele pyannote/wav2vec2 descărcate la build
RUN mkdir -p /data/processed /app/models/whisper /app/models/huggingface

# ── Pre-descărcare modele la build time ──────────────────────
# Modelele sunt bake-uite în imagine → runtime complet offline.
# Dezavantaj: imagine mai mare (~1.5-3 GB extra), dar rulează fără internet.
#
# 1. Model Whisper (faster-whisper via WhisperX)
RUN python3 -c "\
import whisperx, os; \
whisperx.load_model('${WHISPER_MODEL}', device='cpu', compute_type='int8', \
    download_root='/app/models/whisper')"

# 2. Model wav2vec2 pentru aliniere la nivel de cuvânt (română)
#    Fallback la alte limbi dacă 'ro' nu e disponibil.
RUN python3 -c "\
import whisperx; \
try: \
    whisperx.load_align_model(language_code='ro', device='cpu', \
        model_dir='/app/models/huggingface'); \
    print('wav2vec2 ro OK') \
except Exception as e: \
    print(f'wav2vec2 ro indisponibil: {e}; se continuă fără aliniere')"

# 3. Model pyannote pentru diarizare vorbitori (opțional — necesită HF_TOKEN)
#    Dacă HF_TOKEN e gol, pasul e sărit și diarizarea va fi dezactivată.
RUN if [ -n "${HF_TOKEN}" ]; then \
      HF_TOKEN="${HF_TOKEN}" python3 -c "\
import os; \
from pyannote.audio import Pipeline; \
Pipeline.from_pretrained('pyannote/speaker-diarization-3.1', \
    use_auth_token=os.environ['HF_TOKEN']); \
print('pyannote diarization model OK')"; \
    else \
      echo "HF_TOKEN negăsit — modelul pyannote NU va fi descărcat. Diarizarea va fi dezactivată."; \
    fi

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
