# servicies/ingest/src/config.py
# =============================================================
# Configurarea serviciul - citit din variabile de mediu
# =============================================================
# Pydantic BaseSettings citeste automat din .env și validează
# tipurile. Dacă o variabila este lipsă sau de tip greșit,
# aplicatia refuza sa porneasca cu un mesaj de eroare clar.
# Mai bine sa crape la start decat sa crape la miezul noptii! 
# =============================================================

from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """
    Configurarea serviciului de ingestie.
    Valorile sunt cicite din variabile de mediu sau din fișierul .env.
    """

    ### --- Cai de fisiere ---
    inbox_path: Path = Path("/data/inbox")
    audio_storage_path: Path = Path("/data/processed")

    ### --- Limite --- 
    max_file_size_bytes: int = 500 * 1024 * 1024  # 500 MB

    ### ---Formate audio acceptate ---
    allowed_audio_formats: set[str] = {"wav", "mp3", "m4a", "ogg", "flac", "webm"}

    ### --- Redis --- 
    redis_url : str= "redis://localhost:6379"
    redis_transcription_queue: str = "transcription_jobs"

    ### ---Database---
    database_url: str

    ### --- API ---
    api_url: str = "http://api:8080"

    ### ---Comportament 
    log_level: str = "INFO"
    
    #Cat de des verificam inbox-ul pentru fisiere noi (in secunde)
    polling_interval_seconds: int = 10

    # Session Assembly — reconstrucție sesiuni multi-segment
    # Cât timp (secunde) să așteptăm după ultimul segment înainte de a lansa transcrierea.
    # Default 120s = 2 minute. Suficient pentru retry-uri de rețea ale clientului.
    session_timeout_seconds: int = 120
    # Cât de des (secunde) rulează Session Watcher.
    session_watcher_interval_seconds: int = 30

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        # SQLAlchemy folosește "postgresql+asyncpg://" dar asyncpg direct
        # acceptă doar "postgresql://" — normalizăm pentru compatibilitate
        return v.replace("postgresql+asyncpg://", "postgresql://")

    @field_validator("inbox_path", "audio_storage_path")
    @classmethod
    def path_must_exist(cls, v: Path) -> Path:
        """
        Validam ca directoarele exista. 
        Daca nu exista, le cream.
        """
        v.mkdir(parents=True, exist_ok=True)
        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

# Instanta globala - importata de toate modulele
#Singleton - se creeaza o singura data la startul aplicatiei
settings = Settings()