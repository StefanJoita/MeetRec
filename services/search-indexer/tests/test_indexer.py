# services/search-indexer/tests/test_indexer.py
# ============================================================
# Indexarea: context din segmentele vecine, recalcularea la schimbarea
# modelului, verificarea periodică și reconectarea listener-ului.
# ============================================================

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src import bulk_reindexer, listener as listener_module
from src.config import settings
from src.indexer import TranscriptIndexer, with_context

SIG = settings.model_signature


def make_pool(conn):
    acq = AsyncMock()
    acq.__aenter__ = AsyncMock(return_value=conn)
    acq.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(acquire=MagicMock(return_value=acq))


def segment(i, text, stale=True):
    return {"id": f"seg-{i}", "text": text, "stale": stale}


def test_with_context_includes_neighbours():
    texts = ["A.", "B.", "C.", "D."]
    assert with_context(texts, 0, 1) == "A. B."
    assert with_context(texts, 2, 1) == "B. C. D."
    assert with_context(texts, 3, 2) == "B. C. D."
    assert with_context(texts, 1, 0) == "B."


@pytest.mark.asyncio
async def test_only_stale_segments_are_embedded_with_context(monkeypatch):
    monkeypatch.setattr(settings, "embedding_context_segments", 1)
    conn = AsyncMock()
    conn.fetch.return_value = [segment(0, "Bună ziua.", stale=False), segment(1, "Votăm bugetul."),
                               segment(2, "Cine e pentru?", stale=False)]
    embedder = AsyncMock()
    embedder.embed.return_value = [[0.5, 0.5]]

    count = await TranscriptIndexer(make_pool(conn), embedder).index_transcript("t-1")

    assert count == 1
    embedder.embed.assert_awaited_once_with(["Bună ziua. Votăm bugetul. Cine e pentru?"])
    sql, rows = conn.executemany.call_args.args
    assert "embedding_model = $2" in sql
    assert rows == [("[0.50000000,0.50000000]", SIG, "seg-1")]


@pytest.mark.asyncio
async def test_stale_means_missing_or_other_model():
    conn = AsyncMock()
    conn.fetch.return_value = []

    await TranscriptIndexer(make_pool(conn), AsyncMock()).index_transcript("t-1")

    sql, transcript_id, signature = conn.fetch.call_args.args
    assert "embedding IS NULL OR embedding_model IS DISTINCT FROM $2" in sql
    assert signature == SIG


def test_signature_changes_with_model_and_context(monkeypatch):
    before = settings.model_signature
    monkeypatch.setattr(settings, "embedding_context_segments", 2)
    assert settings.model_signature != before
    monkeypatch.setattr(settings, "embedding_model", "alt-model")
    assert settings.model_signature == "alt-model|ctx2"


@pytest.mark.asyncio
async def test_concurrent_requests_are_serialized():
    running, peak = 0, 0

    async def slow_index(transcript_id):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return 1

    indexer = TranscriptIndexer(MagicMock(), AsyncMock())
    indexer._index = slow_index

    await asyncio.gather(*(indexer.index_transcript(f"t-{i}") for i in range(3)))

    assert peak == 1


@pytest.mark.asyncio
async def test_bulk_reindex_newest_first():
    conn = AsyncMock()
    conn.fetch.return_value = [{"id": "t-new"}, {"id": "t-old"}]
    indexer = AsyncMock()
    indexer.index_transcript.side_effect = [3, 2]

    stats = await bulk_reindexer.bulk_reindex(make_pool(conn), indexer)

    assert stats == {"transcripts": 2, "segments": 5}
    assert "ORDER BY t.completed_at DESC" in conn.fetch.call_args.args[0]
    assert [c.args[0] for c in indexer.index_transcript.call_args_list] == ["t-new", "t-old"]


@pytest.mark.asyncio
async def test_sweep_survives_errors_and_stops(monkeypatch):
    monkeypatch.setattr(settings, "sweep_interval_seconds", 0.01)
    stop = asyncio.Event()
    calls = 0

    async def flaky(pool, indexer):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("DB indisponibil")
        if calls == 3:
            stop.set()
        return {"transcripts": 0, "segments": 0}

    monkeypatch.setattr(bulk_reindexer, "bulk_reindex", flaky)

    await asyncio.wait_for(bulk_reindexer.sweep_forever(None, None, stop), timeout=2)

    assert calls == 3


@pytest.mark.asyncio
async def test_listener_reconnects_after_connection_loss(monkeypatch):
    monkeypatch.setattr(listener_module.asyncio, "sleep", AsyncMock())
    lst = listener_module.ChangeListener(AsyncMock())
    connections = []

    def make_conn(closed_after):
        conn = AsyncMock()
        state = {"checks": 0}

        def is_closed():
            state["checks"] += 1
            return state["checks"] > closed_after
        conn.is_closed = MagicMock(side_effect=is_closed)
        return conn

    async def connect(dsn):
        connections.append(make_conn(closed_after=1))
        if len(connections) == 2:
            lst.stop()                                   # a doua conexiune: oprim
        return connections[-1]

    monkeypatch.setattr(listener_module.asyncpg, "connect", connect)

    await asyncio.wait_for(lst.start(), timeout=2)

    assert len(connections) == 2
    connections[0].add_listener.assert_awaited_once()
