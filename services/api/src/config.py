# services/api/src/config.py
from pathlib import Path
from typing import List
from pydantic import field_validator
from pydantic_settings import BaseSettings

_INSECURE_JWT_VALUES = {
    "change_me_to_a_random_32_char_string",
    "secret",
    "changeme",
    "your_secret_key",
    "supersecret",
}


class Settings(BaseSettings):

    # --- Server ---
    # Cu default: valori tehnice, aceleași oriunde, nu sunt secrete
    api_port: int = 8080
    app_env: str = "development"
    log_level: str = "INFO"
    cors_allowed_origins: List[str] = ["https://meeting-transcriber.local"]

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

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        if v.lower() in _INSECURE_JWT_VALUES:
            raise ValueError(
                "\n\n🔐 JWT_SECRET_KEY nu a fost schimbat din valoarea default!\n"
                "   Generează una securizată cu:\n"
                "   python -c \"import secrets; print(secrets.token_hex(32))\"\n"
                "   și seteaz-o în fișierul .env\n"
            )
        if len(v) < 32:
            raise ValueError(
                "JWT_SECRET_KEY trebuie să aibă minimum 32 de caractere."
            )
        return v

    # --- Retenție ---
    retention_days: int = 1095                   # 3 ani

    # --- Search Indexer (pentru semantic search) ---
    search_indexer_url: str = "http://search-indexer:8001"

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()