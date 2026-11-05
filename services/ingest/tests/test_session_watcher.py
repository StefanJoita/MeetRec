# services/ingest/tests/test_session_watcher.py
# BUG-04: sesiunea trimisă deja de /complete (API) nu e publicată a doua oară.

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.database import DatabaseClient
from src.session_watcher import SessionWatcher


def make_client(fetchval_result):
    conn = AsyncMock()
    conn.fetchval.return_value = fetchval_result
    acq = AsyncMock()
    acq.__aenter__ = AsyncMock(return_value=conn)
    acq.__aexit__ = AsyncMock(return_value=False)
    client = DatabaseClient()
    client._pool = MagicMock(acquire=MagicMock(return_value=acq))
    return client, conn


@pytest.mark.asyncio
async def test_mark_dispatched_only_from_queued():
    client, conn = make_client("rec-1")

    assert await client.mark_session_dispatched("rec-1") is True
    sql = conn.fetchval.call_args.args[0]
    assert "AND status = 'queued'" in sql and "RETURNING id" in sql


@pytest.mark.asyncio
async def test_mark_dispatched_false_when_already_sent():
    client, _ = make_client(None)

    assert await client.mark_session_dispatched("rec-1") is False


@pytest.mark.asyncio
async def test_watcher_skips_session_already_dispatched():
    db = MagicMock()
    db.mark_session_dispatched = AsyncMock(side_effect=[False, True])
    publisher = MagicMock()
    watcher = SessionWatcher(database=db, publisher=publisher)
    db.find_expired_sessions = AsyncMock(return_value=["deja-trimisa", "noua"])

    await watcher._run_once()

    publisher.publish_session_job.assert_called_once_with(recording_id="noua", language_hint="ro")
