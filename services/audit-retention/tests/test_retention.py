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


def make_conn():
    """Conexiune asyncpg mock-uită, cu conn.transaction() ca async context manager."""
    conn = AsyncMock()
    tx = AsyncMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx)
    conn.fetch.return_value = []
    return conn


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


class TestDeletePlaybackCopy:

    @pytest.mark.asyncio
    async def test_retention_deletes_original_and_playback_copy(self, tmp_path):
        from datetime import date
        from src.retention_policy import RecordingToDelete, delete_recording

        original = tmp_path / "abc.mp4"
        original.write_bytes(b"v")
        copy = tmp_path / "abc.play.mp3"
        copy.write_bytes(b"a")
        conn = make_conn()
        conn.execute.return_value = "DELETE 1"
        rec = RecordingToDelete(id="r1", title="t", file_path=str(original), retain_until=date(2020, 1, 1))

        assert await delete_recording(pool_with(conn), rec) is True

        assert not original.exists() and not copy.exists()


class TestDeleteSessionChunks:

    @pytest.mark.asyncio
    async def test_retention_deletes_session_chunk_files(self, tmp_path):
        """Bucățile unei sesiuni nelipite nu rămân pe disc după expirare (BUG-01)."""
        from datetime import date
        from src.retention_policy import RecordingToDelete, delete_recording

        original = tmp_path / "s.webm"
        original.write_bytes(b"0")
        chunks = [tmp_path / f"s_{i}.webm" for i in (1, 2)]
        for c in chunks:
            c.write_bytes(b"x")
        conn = make_conn()
        conn.fetch.return_value = [{"file_path": str(c)} for c in chunks]
        conn.execute.return_value = "DELETE 1"
        rec = RecordingToDelete(id="r1", title="t", file_path=str(original), retain_until=date(2020, 1, 1))

        assert await delete_recording(pool_with(conn), rec) is True

        assert not original.exists() and not any(c.exists() for c in chunks)
        conn.transaction.assert_called_once()

    @pytest.mark.asyncio
    async def test_chunks_kept_when_recording_already_deleted(self, tmp_path):
        from datetime import date
        from src.retention_policy import RecordingToDelete, delete_recording

        chunk = tmp_path / "s_1.webm"
        chunk.write_bytes(b"x")
        conn = make_conn()
        conn.fetch.return_value = [{"file_path": str(chunk)}]
        conn.execute.return_value = "DELETE 0"
        rec = RecordingToDelete(id="r1", title="t", file_path=None, retain_until=date(2020, 1, 1))

        assert await delete_recording(pool_with(conn), rec) is False
        assert chunk.exists()
