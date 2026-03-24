# services/stt-worker/tests/test_uploader.py
import uuid
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.uploader import DatabaseUploader, TranscriptMetadata
from src.transcriber import TranscriptSegment

TRANSCRIPT_ID = str(uuid.uuid4())
RECORDING_ID  = str(uuid.uuid4())


def make_segment(idx: int, text: str = "Bună ziua.") -> TranscriptSegment:
    return TranscriptSegment(idx, float(idx*5), float(idx*5+4.9), text, 0.85, "ro")


def make_metadata(**kwargs) -> TranscriptMetadata:
    d = dict(word_count=42, confidence_avg=0.87, processing_time_sec=120,
             language="ro", model_used="whisper-medium")
    d.update(kwargs)
    return TranscriptMetadata(**d)


def make_mock_pool():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"word_count": 42, "confidence_avg": 0.87})
    conn.fetchval = AsyncMock(return_value=0)   # 0 segmente pending → all_done=True
    conn.execute  = AsyncMock()
    conn.executemany = AsyncMock()

    tx = AsyncMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__  = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx)

    acq = AsyncMock()
    acq.__aenter__ = AsyncMock(return_value=conn)
    acq.__aexit__  = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acq)
    pool.close   = AsyncMock()
    return pool, conn


@pytest_asyncio.fixture
async def uploader_with_mock_pool():
    pool, conn = make_mock_pool()
    with patch("src.uploader.asyncpg.create_pool", new=AsyncMock(return_value=pool)):
        u = DatabaseUploader()
        await u.connect()
        yield u, conn


# ── connect / disconnect ──────────────────────────────────────

async def test_connect_creates_pool():
    pool, _ = make_mock_pool()
    with patch("src.uploader.asyncpg.create_pool", new=AsyncMock(return_value=pool)) as mock_c:
        u = DatabaseUploader()
        await u.connect()
        mock_c.assert_called_once()


async def test_disconnect_closes_pool():
    pool, _ = make_mock_pool()
    with patch("src.uploader.asyncpg.create_pool", new=AsyncMock(return_value=pool)):
        u = DatabaseUploader()
        await u.connect()
        await u.disconnect()
        pool.close.assert_called_once()


# ── get_transcript_id ─────────────────────────────────────────

async def test_returns_transcript_id(uploader_with_mock_pool):
    u, conn = uploader_with_mock_pool
    conn.fetchrow.return_value = {"id": TRANSCRIPT_ID}
    assert await u.get_transcript_id(RECORDING_ID) == TRANSCRIPT_ID


async def test_returns_none_if_not_found(uploader_with_mock_pool):
    u, conn = uploader_with_mock_pool
    conn.fetchrow.return_value = None
    assert await u.get_transcript_id(RECORDING_ID) is None


async def test_queries_by_recording_id(uploader_with_mock_pool):
    u, conn = uploader_with_mock_pool
    conn.fetchrow.return_value = {"id": TRANSCRIPT_ID}
    await u.get_transcript_id(RECORDING_ID)
    assert RECORDING_ID in conn.fetchrow.call_args[0]


# ── mark_processing ───────────────────────────────────────────

async def test_mark_processing_two_updates(uploader_with_mock_pool):
    u, conn = uploader_with_mock_pool
    await u.mark_processing(TRANSCRIPT_ID, RECORDING_ID, "whisper-medium")
    assert conn.execute.call_count == 2


async def test_mark_processing_sets_processing_on_transcript(uploader_with_mock_pool):
    u, conn = uploader_with_mock_pool
    await u.mark_processing(TRANSCRIPT_ID, RECORDING_ID, "whisper-medium")
    sql = conn.execute.call_args_list[0][0][0]
    assert "processing" in sql and "transcripts" in sql


async def test_mark_processing_sets_transcribing_on_recording(uploader_with_mock_pool):
    u, conn = uploader_with_mock_pool
    await u.mark_processing(TRANSCRIPT_ID, RECORDING_ID, "whisper-medium")
    sql = conn.execute.call_args_list[1][0][0]
    assert "transcribing" in sql and "recordings" in sql


async def test_mark_processing_uses_transaction(uploader_with_mock_pool):
    u, conn = uploader_with_mock_pool
    await u.mark_processing(TRANSCRIPT_ID, RECORDING_ID, "whisper-medium")
    conn.transaction.assert_called_once()


# ── save_results ──────────────────────────────────────────────

async def test_save_results_calls_executemany(uploader_with_mock_pool):
    u, conn = uploader_with_mock_pool
    await u.save_results(TRANSCRIPT_ID, RECORDING_ID, [make_segment(0)], make_metadata())
    conn.executemany.assert_called_once()


async def test_save_results_correct_segment_count(uploader_with_mock_pool):
    u, conn = uploader_with_mock_pool
    segs = [make_segment(i) for i in range(7)]
    await u.save_results(TRANSCRIPT_ID, RECORDING_ID, segs, make_metadata())
    _, tuples = conn.executemany.call_args[0]
    assert len(tuples) == 7


async def test_save_results_tuples_not_dicts(uploader_with_mock_pool):
    u, conn = uploader_with_mock_pool
    await u.save_results(TRANSCRIPT_ID, RECORDING_ID, [make_segment(0)], make_metadata())
    _, tuples = conn.executemany.call_args[0]
    assert all(isinstance(t, tuple) for t in tuples)


async def test_save_results_sql_has_on_conflict(uploader_with_mock_pool):
    u, conn = uploader_with_mock_pool
    await u.save_results(TRANSCRIPT_ID, RECORDING_ID, [make_segment(0)], make_metadata())
    sql = conn.executemany.call_args[0][0]
    assert "ON CONFLICT" in sql.upper()


async def test_save_results_marks_transcript_completed(uploader_with_mock_pool):
    u, conn = uploader_with_mock_pool
    # fetchrow returnează structura agregată folosită când all_done=True
    conn.fetchrow.return_value = {"word_count": 42, "confidence_avg": 0.87}
    await u.save_results(TRANSCRIPT_ID, RECORDING_ID, [make_segment(0)], make_metadata())
    sqls = [c[0][0] for c in conn.execute.call_args_list]
    assert any("completed" in s and "transcripts" in s for s in sqls)


async def test_save_results_marks_recording_completed(uploader_with_mock_pool):
    u, conn = uploader_with_mock_pool
    conn.fetchrow.return_value = {"word_count": 42, "confidence_avg": 0.87}
    await u.save_results(TRANSCRIPT_ID, RECORDING_ID, [make_segment(0)], make_metadata())
    sqls = [c[0][0] for c in conn.execute.call_args_list]
    assert any("completed" in s and "recordings" in s for s in sqls)


async def test_save_results_passes_word_count(uploader_with_mock_pool):
    u, conn = uploader_with_mock_pool
    # word_count vine din query-ul agregat (agg["word_count"]), nu din metadata
    conn.fetchrow.return_value = {"word_count": 123, "confidence_avg": 0.87}
    await u.save_results(TRANSCRIPT_ID, RECORDING_ID, [make_segment(0)], make_metadata())
    flat = [p for c in conn.execute.call_args_list for p in c[0][1:]]
    assert 123 in flat


async def test_save_results_uses_transaction(uploader_with_mock_pool):
    u, conn = uploader_with_mock_pool
    await u.save_results(TRANSCRIPT_ID, RECORDING_ID, [make_segment(0)], make_metadata())
    conn.transaction.assert_called_once()


async def test_save_results_empty_segments(uploader_with_mock_pool):
    u, conn = uploader_with_mock_pool
    await u.save_results(TRANSCRIPT_ID, RECORDING_ID, [], make_metadata(word_count=0))
    conn.executemany.assert_called_once()
    _, tuples = conn.executemany.call_args[0]
    assert tuples == []


# ── mark_failed ───────────────────────────────────────────────

async def test_mark_failed_sets_transcript_failed(uploader_with_mock_pool):
    u, conn = uploader_with_mock_pool
    await u.mark_failed(TRANSCRIPT_ID, RECORDING_ID, "Eroare test")
    sqls = [c[0][0] for c in conn.execute.call_args_list]
    assert any("failed" in s and "transcripts" in s for s in sqls)


async def test_mark_failed_sets_recording_failed(uploader_with_mock_pool):
    u, conn = uploader_with_mock_pool
    await u.mark_failed(TRANSCRIPT_ID, RECORDING_ID, "Eroare test")
    sqls = [c[0][0] for c in conn.execute.call_args_list]
    assert any("failed" in s and "recordings" in s for s in sqls)


async def test_mark_failed_saves_error_message(uploader_with_mock_pool):
    u, conn = uploader_with_mock_pool
    msg = "FileNotFoundError: /data/missing.mp3"
    await u.mark_failed(TRANSCRIPT_ID, RECORDING_ID, msg)
    flat = [p for c in conn.execute.call_args_list for p in c[0][1:]]
    assert msg in flat


async def test_mark_failed_uses_transaction(uploader_with_mock_pool):
    u, conn = uploader_with_mock_pool
    await u.mark_failed(TRANSCRIPT_ID, RECORDING_ID, "eroare")
    conn.transaction.assert_called_once()
