# services/audit-retention/tests/test_retention.py
# ============================================================
# Retenția înregistrărilor și setările din Administrare → Setări
# ============================================================

import json
from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest

from src import runtime_settings
from src.config import settings
from src.retention_policy import fetch_expired_recordings


def pool_with(conn):
    acq = AsyncMock()
    acq.__aenter__ = AsyncMock(return_value=conn)
    acq.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(acquire=MagicMock(return_value=acq))


@pytest.fixture(autouse=True)
def restore_settings(monkeypatch):
    for k in runtime_settings.KEYS:
        monkeypatch.setattr(settings, k, getattr(settings, k))


class TestExpiredRecordings:

    @pytest.mark.asyncio
    async def test_uses_created_at_plus_retention_days_when_retain_until_missing(self):
        conn = AsyncMock()
        conn.fetch.return_value = []
        settings.retention_days = 400

        await fetch_expired_recordings(pool_with(conn))

        sql, days = conn.fetch.call_args.args
        assert "COALESCE(retain_until, (created_at + make_interval(days => $1))::date)" in sql
        assert days == 400


class TestRefresh:

    @pytest.mark.asyncio
    async def test_values_from_table_are_applied(self):
        conn = AsyncMock()
        conn.fetch.return_value = [{"key": "retention_days", "value": json.dumps(730)}]

        changed = await runtime_settings.refresh(pool_with(conn))

        assert settings.retention_days == 730
        assert changed == {"retention_days": 730}

    @pytest.mark.asyncio
    async def test_reset_returns_to_env_value(self):
        settings.retention_days = 730
        conn = AsyncMock()
        conn.fetch.return_value = []

        await runtime_settings.refresh(pool_with(conn))

        assert settings.retention_days == runtime_settings._ENV["retention_days"]

    @pytest.mark.asyncio
    async def test_missing_table_uses_env_values(self):
        conn = AsyncMock()
        conn.fetch.side_effect = asyncpg.UndefinedTableError("app_settings")

        await runtime_settings.refresh(pool_with(conn))

        assert settings.retention_days == runtime_settings._ENV["retention_days"]

    @pytest.mark.asyncio
    async def test_db_error_keeps_current_values(self):
        settings.audit_log_retention_days = 999
        conn = AsyncMock()
        conn.fetch.side_effect = ConnectionError("db down")

        assert await runtime_settings.refresh(pool_with(conn)) == {}
        assert settings.audit_log_retention_days == 999
