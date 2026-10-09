#!/usr/bin/env python3
# install/models/download-models.py
# ============================================================
# Descarcă TOATE modelele ML necesare rulării offline și le pune
# în build context-ul serviciilor, de unde Dockerfile-urile le
# copiază în imagini (COPY models/ ...).
#
# Rulat pe o mașină CU internet, înainte de `docker compose build`.
#
#   python install/models/download-models.py                 # implicit: large-v3
#   python install/models/download-models.py --whisper-model medium
#   python install/models/download-models.py --skip-diarization
#
# Dependențe: pip install "huggingface_hub>=0.26,<1.0" nltk
# Token HuggingFace (doar pentru diarizare): variabila HF_TOKEN sau
# linia HF_TOKEN=... din .env (rădăcina repo-ului).
#
# Structura rezultată (layout cache HuggingFace, folosit cu HF_HUB_OFFLINE=1):
#   services/stt-worker/models/whisper/models--Systran--faster-whisper-<model>/
#   services/stt-worker/models/huggingface/hub/models--gigant--romanian-wav2vec2/
#   services/stt-worker/models/huggingface/hub/models--pyannote--speaker-diarization-community-1/
#   services/stt-worker/models/nltk_data/tokenizers/punkt_tab/
#   services/search-indexer/models/models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2/
# ============================================================

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STT_MODELS = REPO_ROOT / "services" / "stt-worker" / "models"
INDEXER_MODELS = REPO_ROOT / "services" / "search-indexer" / "models"

# Numele de model WhisperX → repo-ul faster-whisper (CTranslate2) folosit de faster-whisper
WHISPER_REPOS = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v2": "Systran/faster-whisper-large-v2",
    "large-v3": "Systran/faster-whisper-large-v3",
    "large": "Systran/faster-whisper-large-v3",
}

# Model de aliniere wav2vec2 pentru română (whisperx 3.8.6, alignment.py)
ALIGN_REPO = "gigant/romanian-wav2vec2"

# Model de diarizare implicit în whisperx 3.8.6 (pyannote-audio 4.x) — GATED
DIARIZATION_REPO = "pyannote/speaker-diarization-community-1"

# Model embeddings pentru search-indexer
EMBEDDING_REPO = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# Formatele pe care nu le folosim (PyTorch pe CPU) — economisim GB
SKIP_FORMATS = ["*.onnx", "onnx/*", "openvino/*", "*.h5", "*.msgpack", "tf_model*", "flax_model*", "rust_model*"]


def read_hf_token() -> str | None:
    token = os.environ.get("HF_TOKEN", "").strip()
    if token:
        return token
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("HF_TOKEN="):
                value = line.split("=", 1)[1].split("#", 1)[0].strip().strip('"').strip("'")
                return value or None
    return None


def download(repo_id: str, cache_dir: Path, token: str | None = None, **kwargs) -> Path:
    from huggingface_hub import snapshot_download

    print(f"→ {repo_id}  →  {cache_dir.relative_to(REPO_ROOT)}", flush=True)
    path = snapshot_download(
        repo_id=repo_id,
        cache_dir=str(cache_dir),
        token=token,
        **kwargs,
    )
    size = sum(f.stat().st_size for f in Path(path).rglob("*") if f.is_file())
    print(f"  ✓ {size / 1024**2:,.0f} MB", flush=True)
    return Path(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--whisper-model", default=os.environ.get("WHISPER_MODEL", "large-v3"),
                        choices=sorted(WHISPER_REPOS))
    parser.add_argument("--skip-diarization", action="store_true",
                        help="Nu descărca modelul pyannote (diarizarea va fi indisponibilă offline).")
    args = parser.parse_args()

    # ── 1. Whisper (faster-whisper / CTranslate2) ─────────────
    # whisperx.load_model(download_root=/app/models/whisper) → cache HF în acel director
    download(
        WHISPER_REPOS[args.whisper_model],
        STT_MODELS / "whisper",
        allow_patterns=["config.json", "preprocessor_config.json", "model.bin",
                        "tokenizer.json", "vocabulary.*"],
    )

    # ── 2. Aliniere wav2vec2 (română) ─────────────────────────
    # load_align_model(model_dir=None) → cache HF implicit = $HF_HOME/hub
    # Doar ce citesc Wav2Vec2Processor + Wav2Vec2ForCTC: repo-ul mai conține un model
    # de limbă 5-gram, o copie pytorch_model.bin și artefacte de antrenare (~1.7 GB inutili).
    download(
        ALIGN_REPO,
        STT_MODELS / "huggingface" / "hub",
        allow_patterns=["config.json", "preprocessor_config.json", "tokenizer_config.json",
                        "vocab.json", "special_tokens_map.json", "added_tokens.json",
                        "model.safetensors"],
    )

    # ── 3. Diarizare pyannote (gated) ─────────────────────────
    if args.skip_diarization:
        print("→ diarizare: omisă (--skip-diarization)")
    else:
        token = read_hf_token()
        if not token:
            print(
                "\n❌ HF_TOKEN lipsește. Diarizarea necesită un token HuggingFace și acceptarea\n"
                f"   termenilor pe https://huggingface.co/{DIARIZATION_REPO}\n"
                "   Pune HF_TOKEN=... în .env sau rulează cu --skip-diarization.",
                file=sys.stderr,
            )
            return 2
        download(DIARIZATION_REPO, STT_MODELS / "huggingface" / "hub", token=token,
                 ignore_patterns=SKIP_FORMATS)

    # ── 4. NLTK punkt_tab ─────────────────────────────────────
    # whisperx/alignment.py descarcă punkt_tab la prima aliniere dacă lipsește
    import nltk

    nltk_dir = STT_MODELS / "nltk_data"
    print(f"→ nltk punkt_tab  →  {nltk_dir.relative_to(REPO_ROOT)}", flush=True)
    if not nltk.download("punkt_tab", download_dir=str(nltk_dir), quiet=True, raise_on_error=True):
        print("❌ Descărcarea punkt_tab a eșuat.", file=sys.stderr)
        return 1
    print("  ✓ punkt_tab", flush=True)

    # ── 5. Embeddings (search-indexer) ────────────────────────
    # SentenceTransformer(name, cache_folder=/app/models) → cache HF direct în acel director
    download(EMBEDDING_REPO, INDEXER_MODELS, ignore_patterns=SKIP_FORMATS + ["pytorch_model.bin"])

    print("\n✅ Toate modelele au fost descărcate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
