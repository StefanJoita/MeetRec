# alembic/env.py — configurare runtime Alembic
# ============================================================
# Conectează Alembic la baza de date și la modelele SQLAlchemy.
# Suportă atât migrări online (cu conexiune activă) cât și offline (SQL dump).
# ============================================================

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Importăm configurarea aplicației pentru DATABASE_URL
from src.config import settings

# Importăm Base + toate modelele pentru autodetect
from src.models.base import Base
from src.models.recording import Recording           # noqa: F401
from src.models.transcript import Transcript, TranscriptSegment  # noqa: F401
from src.models.audit_log import AuditLog, User     # noqa: F401

# Obiectul de configurare Alembic (din alembic.ini)
config = context.config

# Setăm URL-ul din Settings (suprascrie [alembic] sqlalchemy.url din ini)
config.set_main_option("sqlalchemy.url", settings.database_url)

# Configurare logging din ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadatele SQLAlchemy — Alembic detectează automat modificările de schemă
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generează SQL fără conexiune la DB (util pentru review înainte de aplicare)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Rulează migrările cu engine async (asyncpg)."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Rulează migrările cu conexiune activă la DB."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
