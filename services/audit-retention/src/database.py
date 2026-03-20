# services/audit-retention/src/database.py
# Connection pool asyncpg — același pattern ca ingest service.

from typing import Optional
import asyncpg
import structlog

from src.config import settings

logger = structlog.get_logger(__name__)


class DatabaseClient:

    def __init__(self):
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        logger.info("connecting_to_db")
        self._pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=1,
            max_size=5,
            command_timeout=60,
        )
        logger.info("database_connected")

    async def disconnect(self) -> None:
        if self._pool:
            await self._pool.close()
            logger.info("database_disconnected")

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("DatabaseClient.connect() nu a fost apelat.")
        return self._pool
