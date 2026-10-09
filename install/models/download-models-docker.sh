#!/usr/bin/env bash
# =============================================================
# download-models-docker.sh — rulează install/models/download-models.py
# într-un container python:3.11-slim temporar.
# =============================================================
# Avantaj: pe host e nevoie doar de Docker (nu de Python/pip/venv).
# Necesită internet. HF_TOKEN e citit din mediu sau din .env (doar pentru diarizare).
#
# Folosire:
#   bash install/models/download-models-docker.sh [argumente download-models.py]
#   ex: bash install/models/download-models-docker.sh --whisper-model large-v3
#       bash install/models/download-models-docker.sh --skip-diarization
# =============================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Fișierele create în bind mount trebuie să aparțină userului curent, nu lui root
USER_FLAGS=()
if [[ "$(uname -s)" == "Linux" ]]; then
    USER_FLAGS=(--user "$(id -u):$(id -g)")
fi

docker run --rm "${USER_FLAGS[@]}" \
    -v "$REPO_ROOT:/repo" -w /repo \
    -e HF_TOKEN="${HF_TOKEN:-}" \
    -e HOME=/tmp \
    -e PYTHONPATH=/tmp/pydeps \
    -e PYTHONIOENCODING=utf-8 \
    -e HF_HUB_DISABLE_PROGRESS_BARS=1 \
    python:3.11-slim \
    sh -c 'pip install -q --disable-pip-version-check --target /tmp/pydeps "huggingface_hub>=0.26,<1.0" "nltk==3.9.1" \
           && python install/models/download-models.py "$@"' _ "$@"
