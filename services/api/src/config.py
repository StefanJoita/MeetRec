# services/api/src/config.py
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):

    # --- Server ---
    # Cu default: valori tehnice, aceleași oriunde, nu sunt secrete
    api_port: int = 8080
    app_env: str = "development"
    log_level: str = "INFO"

    # --- Database ---
    # Fără default: conține parola → dacă lipsește din .env = eroare la startup
    database_url: str

    # --- Redis ---
    redis_url: str = "redis://redis:6379"        # nu e secret
    redis_transcription_queue: str = "transcription_jobs"

    # --- Storage ---
    # Cu default: căile sunt aceleași în orice container Docker
    audio_storage_path: Path = Path("/data/processed")
    export_path: Path = Path("/data/exports")
    inbox_path: Path = Path("/data/inbox")
    max_file_size_bytes: int = 524_288_000       # 500MB

    # --- Auth (JWT) ---
    # Fără default: cheie criptografică → dacă lipsește din .env = eroare la startup
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"                 # algoritm standard, nu e secret
    jwt_expire_minutes: int = 480                # 8 ore

    # --- Retenție ---
    retention_days: int = 1095                   # 3 ani

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()