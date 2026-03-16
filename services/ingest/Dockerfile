# services/ingest/Dockerfile
# ============================================================
# Fiecare linie "FROM/RUN/COPY" = un "strat" (layer) în imagine
# Docker memorează fiecare strat separat → rebuild rapid
# (dacă schimbi codul, reconstruiește DOAR stratul cu codul,
#  nu și pe cel cu dependențele)
# ============================================================

# Stratul 1: Imaginea de bază
# python:3.11-slim = Python 3.11 pe Debian minimal (~150MB)
# vs python:3.11 = Python complet (~900MB) — nu avem nevoie de tot
FROM python:3.11-slim

# Stratul 2: Metadate (documentare, nu afectează funcționalitatea)
LABEL service="ingest" \
      description="Monitorizează inbox și procesează fișiere audio noi"

# Stratul 3: Variabile de build
# PYTHONDONTWRITEBYTECODE: nu crea fișiere .pyc (economisim spațiu)
# PYTHONUNBUFFERED: afișează logurile imediat (nu le bufferiza)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_HOME=/app

# Stratul 4: Instalare dependențe sistem
# ffmpeg: necesar pentru pydub (verificare audio corupt)
# Instalăm dependențele sistem ÎNAINTE de codul Python
# → dacă schimbăm codul, nu reinstalăm ffmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*
    # rm = curăță cache-ul apt (reduce dimensiunea imaginii)

# Stratul 5: Creăm directorul de lucru
WORKDIR $APP_HOME

# Stratul 6: Instalare dependențe Python
# Copiem DOAR requirements.txt mai întâi (nu tot codul)
# De ce? Docker caching:
#   - Dacă requirements.txt nu s-a schimbat → strat din cache
#   - Dacă ai schimbat doar codul → sare direct la pasul următor
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stratul 7: Copiem codul aplicației
# Acesta se schimbă des → e ultimul strat (pentru cache eficient)
COPY src/ ./src/

# Stratul 8: Creăm directoarele necesare în container
RUN mkdir -p /data/inbox /data/processed

# Nu expunem niciun port: Ingest Service nu ascultă conexiuni,
# el doar monitorizează fișiere și publică în Redis

# Comanda de start
CMD ["python", "-m", "src.main"]