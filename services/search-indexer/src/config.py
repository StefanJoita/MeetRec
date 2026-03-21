# services/search-indexer/src/config.py

from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Conexiune DB
    database_url: str

    # Modelul de embeddings
    # paraphrase-multilingual-MiniLM-L12-v2:
    #   - 384 dimensiuni, ~120MB
    #   - suport nativ limbă română
    #   - rapid pe CPU (~50ms/segment)
    embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    embedding_model_path: Path = Path("/app/models")
    embedding_batch_size: int = 32  # segmente procesate simultan

    # Canalul PostgreSQL LISTEN/NOTIFY
    notify_channel: str = "transcript_ready"

    # Port HTTP pentru /embed endpoint (apelat de API)
    http_port: int = 8001

    log_level: str = "INFO"

    @field_validator("database_url")
    @classmethod
    def normalize_url(cls, v: str) -> str:
        return v.replace("postgresql+asyncpg://", "postgresql://")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


settings = Settings()
