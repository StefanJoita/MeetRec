# services/audit-retention/src/config.py
# Configurare citită din variabile de mediu (același pattern ca restul serviciilor).

from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Conexiune DB
    database_url: str

    # Politici de retenție (din .env)
    retention_days: int = 1095          # 3 ani pentru înregistrări audio
    audit_log_retention_days: int = 2190  # 6 ani pentru audit logs

    # Unde sunt fișierele audio pe disc
    audio_storage_path: Path = Path("/data/processed")

    # Cât de des rulăm verificarea de retenție (în secunde)
    # Default: o dată pe zi (86400s)
    retention_check_interval_seconds: int = 86400

    log_level: str = "INFO"

    @field_validator("database_url")
    @classmethod
    def normalize_url(cls, v: str) -> str:
        # asyncpg direct acceptă "postgresql://" nu "postgresql+asyncpg://"
        return v.replace("postgresql+asyncpg://", "postgresql://")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


settings = Settings()
