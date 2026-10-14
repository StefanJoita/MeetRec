# services/ingest/tests/test_processor_settings.py
# Limita de mărime din Administrare → Setări (app_settings.max_file_size_mb)

from unittest.mock import AsyncMock, MagicMock

import pytest

from src import processor as processor_module
from src.config import settings
from src.processor import FileProcessor


@pytest.fixture
def proc(monkeypatch):
    monkeypatch.setattr(settings, "max_file_size_bytes", settings.max_file_size_bytes)
    database = MagicMock()
    database.get_app_setting = AsyncMock()
    return FileProcessor(validator=MagicMock(), storage=MagicMock(), database=database, publisher=MagicMock())


@pytest.mark.asyncio
async def test_limit_from_admin_settings(proc):
    proc.database.get_app_setting.return_value = 100

    await proc._refresh_max_file_size()

    proc.database.get_app_setting.assert_awaited_with("max_file_size_mb")
    assert settings.max_file_size_bytes == 100 * 1024 * 1024


@pytest.mark.asyncio
async def test_no_admin_setting_uses_env_value(proc):
    settings.max_file_size_bytes = 1
    proc.database.get_app_setting.return_value = None

    await proc._refresh_max_file_size()

    assert settings.max_file_size_bytes == processor_module.ENV_MAX_FILE_SIZE_BYTES


@pytest.mark.asyncio
async def test_db_error_keeps_current_limit(proc):
    settings.max_file_size_bytes = 12345
    proc.database.get_app_setting.side_effect = ConnectionError("db down")

    await proc._refresh_max_file_size()

    assert settings.max_file_size_bytes == 12345
