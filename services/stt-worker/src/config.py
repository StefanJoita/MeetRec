from typing import Optional
# services/stt-worker/src/config.py
# ============================================================
# Configurarea STT Worker — citit din variabile de mediu
# ============================================================
# Pattern identic cu services/ingest/src/config.py, cu o
# diferență critică la validatorul de path-uri:
#
# INGEST validator face:   v.mkdir(parents=True, exist_ok=True)
# STT WORKER validator face: raise ValueError dacă NU există
#
# De ce diferit?
#   Ingest-ul DEȚINE folderele → le creează dacă lipsesc.
#   STT Worker-ul PRIMEȘTE audio_storage_path montat :ro (read-only)
#   în docker-compose. mkdir pe un volum read-only = PermissionError
#   la startup, chiar dacă directorul există deja!
#   Mai sigur: verificăm că există, nu îl creăm.
# ============================================================

from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Configurarea STT Worker.
    Valorile sunt citite din variabile de mediu sau din fișierul .env.
    """

    # --- Cale stocare audio (montat read-only din NFS) ---
    # Workerul CITEȘTE fișierele audio de aici, nu scrie
    audio_storage_path: Path = Path("/data/processed")

    # --- Redis — coada de joburi ---
    redis_url: str = "redis://localhost:6379"
    redis_transcription_queue: str = "transcription_jobs"

    # --- Database (fără default — obligatoriu în .env) ---
    # Format: postgresql://user:pass@host:port/dbname
    database_url: str

    # --- Whisper STT ---
    # Modelul de folosit: tiny / base / small / medium / large
    # Compromis: larger = mai precis, mai lent, mai mult RAM
    #   tiny:   ~1 GB RAM, rapid, calitate scăzută
    #   base:   ~1 GB RAM
    #   small:  ~2 GB RAM
    #   medium: ~5 GB RAM
    #   large:  ~10 GB RAM  ← recomandat pentru română (acuratețe maximă)
    whisper_model: str = "large"

    # Unde sunt descărcate / cachate modelele Whisper
    # Montat ca volum Docker persistent → nu se re-descarcă la restart
    whisper_model_path: Path = Path("/app/models")

    # Limba principală: "ro" = română
    # Passată la whisper.transcribe(language=...) pentru precizie mai bună
    whisper_primary_language: str = "ro"

    # Câte joburi simultan (1 = procesare serială)
    stt_worker_concurrency: int = 1


    # Tipul de calcul pentru faster-whisper (CTranslate2)
    # "int8" cel mai rapid pe CPU, "float32" mai compatibil
    whisper_compute_type: str = "int8"

    # --- Diarizare vorbitori ---
    diarization_enabled: bool = False
    hf_token: str = ""
    min_speakers: Optional[int] = None
    max_speakers: Optional[int] = None

    @field_validator("min_speakers", "max_speakers", mode="before")
    @classmethod
    def _empty_str_to_none(cls, v: object) -> object:
        """String gol din env var ("") → None, înainte ca Pydantic să parseze ca int."""
        if isinstance(v, str) and not v.strip():
            return None
        return v
    # --- Logging ---
    log_level: str = "INFO"

    # ── Validatoare ──────────────────────────────────────────

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        # SQLAlchemy folosește "postgresql+asyncpg://" dar asyncpg direct
        # acceptă doar "postgresql://" — normalizăm pentru compatibilitate
        return v.replace("postgresql+asyncpg://", "postgresql://")

    @field_validator("audio_storage_path")
    @classmethod
    def audio_path_must_exist(cls, v: Path) -> Path:
        """
        Verificăm că directorul de audio EXISTĂ.
        NU îl creăm — e montat read-only din docker-compose.

        Eroarea la startup e intenționată (fail-fast):
        mai bine crape acum cu mesaj clar decât să eșueze
        mai târziu cu FileNotFoundError la prima transcriere.
        """
        if not v.exists():
            raise ValueError(
                f"audio_storage_path '{v}' nu există. "
                f"Verifică că volumul Docker e montat corect."
            )
        return v

    @field_validator("whisper_model_path")
    @classmethod
    def model_path_create_if_missing(cls, v: Path) -> Path:
        """
        Directorul pentru modele Whisper îl CREĂM dacă lipsește.
        Motivul: workerul descarcă modelul la primul start.
        Fără director → whisper.load_model() eșuează.
        """
        v.mkdir(parents=True, exist_ok=True)
        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


# Instanță globală — importată de toate modulele
# Singleton: se creează o singură dată la startul aplicației
settings = Settings()
