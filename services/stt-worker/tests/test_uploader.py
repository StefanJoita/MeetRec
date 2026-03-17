# services/stt-worker/tests/test_uploader.py
# ============================================================
# Teste pentru DatabaseUploader
# ============================================================
# Mockăm asyncpg.create_pool() și conexiunile sale.
# Nu avem nevoie de PostgreSQL real.
#
# Ce testăm:
#   - SQL-urile corecte sunt trimise la DB
#   - executemany() e apelat pentru bulk insert
#   - Tranzacțiile sunt folosite (conn.transaction())
#   - mark_failed() salvează error_message
#   - Numărul corect de segmente e inserat
# ============================================================

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from src.uploader import DatabaseUploader, TranscriptMetadata
from src.transcriber import TranscriptSegment


# ── Helpers ───────────────────────────────────────────────────

TRANSCRIPT_ID = str(uuid.uuid4())
RECORDING_ID  = str(uuid.uuid4())


def make_segment(idx: int, text: str = "Bună ziua.") -> TranscriptSegment:
    return TranscriptSegment(
        segment_index=idx,
        start_time=float(idx * 5),
        end_time=float(idx * 5 + 4.9),
        text=text,
        confidence=0.85,
        language="ro",
    )


def make_metadata(**kwargs) -> TranscriptMetadata:
    defaults = dict(
        word_count=42,
        confidence_avg=0.87,
        processing_time_sec=120,
        language="ro",
        model_used="whisper-medium",
    )
    defaults.update(kwargs)
    return TranscriptMetadata(**defaults)


# ── Fixture: mock asyncpg pool ────────────────────────────────

def make_mock_pool():
    """
    Construiește un mock asyncpg pool cu connection și transaction.

    asyncpg API:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(...)
                await conn.executemany(...)

    Mockăm fiecare nivel: pool → conn → transaction
    """
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"id": TRANSCRIPT_ID})
    conn.execute = AsyncMock()
    conn.executemany = AsyncMock()

    # transaction() returnează un async context manager
    tx_cm = AsyncMock()
    tx_cm.__aenter__ = AsyncMock(return_value=None)
    tx_cm.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx_cm)

    # acquire() returnează un async context manager care yield-uiește conn
    acquire_cm = AsyncMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_cm)
    pool.close = AsyncMock()

    return pool, conn


# ── Fixture ───────────────────────────────────────────────────

@pytest.fixture
async def uploader_with_mock_pool():
    """DatabaseUploader cu pool mock — fără PostgreSQL real."""
    pool, conn = make_mock_pool()
    with patch("src.uploader.asyncpg.create_pool", new=AsyncMock(return_value=pool)):
        u = DatabaseUploader()
        await u.connect()
        yield u, conn


# ============================================================
# TEST: connect / disconnect
# ============================================================

class TestConnect:

    @pytest.mark.asyncio
    async def test_connect_creates_pool(self):
        """connect() trebuie să apeleze asyncpg.create_pool()."""
        pool, _ = make_mock_pool()
        with patch("src.uploader.asyncpg.create_pool", new=AsyncMock(return_value=pool)) as mock_create:
            u = DatabaseUploader()
            await u.connect()
            mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_closes_pool(self):
        """disconnect() trebuie să apeleze pool.close()."""
        pool, _ = make_mock_pool()
        with patch("src.uploader.asyncpg.create_pool", new=AsyncMock(return_value=pool)):
            u = DatabaseUploader()
            await u.connect()
            await u.disconnect()
            pool.close.assert_called_once()


# ============================================================
# TEST: get_transcript_id
# ============================================================

class TestGetTranscriptId:

    @pytest.mark.asyncio
    async def test_returns_transcript_id(self, uploader_with_mock_pool):
        """get_transcript_id() trebuie să returneze ID-ul din DB."""
        u, conn = uploader_with_mock_pool
        conn.fetchrow.return_value = {"id": TRANSCRIPT_ID}

        result = await u.get_transcript_id(RECORDING_ID)
        assert result == TRANSCRIPT_ID

    @pytest.mark.asyncio
    async def test_returns_none_if_not_found(self, uploader_with_mock_pool):
        """Dacă rândul nu există, returnăm None (nu aruncăm excepție)."""
        u, conn = uploader_with_mock_pool
        conn.fetchrow.return_value = None

        result = await u.get_transcript_id(RECORDING_ID)
        assert result is None

    @pytest.mark.asyncio
    async def test_queries_by_recording_id(self, uploader_with_mock_pool):
        """Query-ul trebuie să filtreze după recording_id."""
        u, conn = uploader_with_mock_pool
        conn.fetchrow.return_value = {"id": TRANSCRIPT_ID}

        await u.get_transcript_id(RECORDING_ID)

        # Verificăm că recording_id e transmis ca parametru la query
        call_args = conn.fetchrow.call_args
        assert RECORDING_ID in call_args[0]


# ============================================================
# TEST: mark_processing
# ============================================================

class TestMarkProcessing:

    @pytest.mark.asyncio
    async def test_calls_execute_twice(self, uploader_with_mock_pool):
        """mark_processing() trebuie să facă 2 UPDATE-uri: transcripts + recordings."""
        u, conn = uploader_with_mock_pool

        await u.mark_processing(TRANSCRIPT_ID, RECORDING_ID, "whisper-medium")

        assert conn.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_updates_transcript_status_to_processing(self, uploader_with_mock_pool):
        """Primul UPDATE trebuie să seteze status='processing' pe transcripts."""
        u, conn = uploader_with_mock_pool

        await u.mark_processing(TRANSCRIPT_ID, RECORDING_ID, "whisper-medium")

        first_call_sql = conn.execute.call_args_list[0][0][0]
        assert "processing" in first_call_sql
        assert "transcripts" in first_call_sql

    @pytest.mark.asyncio
    async def test_updates_recording_status_to_transcribing(self, uploader_with_mock_pool):
        """Al doilea UPDATE trebuie să seteze status='transcribing' pe recordings."""
        u, conn = uploader_with_mock_pool

        await u.mark_processing(TRANSCRIPT_ID, RECORDING_ID, "whisper-medium")

        second_call_sql = conn.execute.call_args_list[1][0][0]
        assert "transcribing" in second_call_sql
        assert "recordings" in second_call_sql

    @pytest.mark.asyncio
    async def test_uses_transaction(self, uploader_with_mock_pool):
        """mark_processing() trebuie să ruleze în tranzacție."""
        u, conn = uploader_with_mock_pool

        await u.mark_processing(TRANSCRIPT_ID, RECORDING_ID, "whisper-medium")

        conn.transaction.assert_called_once()


# ============================================================
# TEST: save_results
# ============================================================

class TestSaveResults:

    @pytest.mark.asyncio
    async def test_executemany_called_for_segments(self, uploader_with_mock_pool):
        """
        executemany() trebuie apelat pentru bulk insert segmente.
        NU execute() individual per segment.
        """
        u, conn = uploader_with_mock_pool
        segments = [make_segment(i) for i in range(5)]

        await u.save_results(TRANSCRIPT_ID, RECORDING_ID, segments, make_metadata())

        conn.executemany.assert_called_once()

    @pytest.mark.asyncio
    async def test_executemany_receives_correct_count(self, uploader_with_mock_pool):
        """executemany() trebuie să primească exact N tuple-uri pentru N segmente."""
        u, conn = uploader_with_mock_pool
        n = 7
        segments = [make_segment(i) for i in range(n)]

        await u.save_results(TRANSCRIPT_ID, RECORDING_ID, segments, make_metadata())

        _, tuples = conn.executemany.call_args[0]
        assert len(tuples) == n

    @pytest.mark.asyncio
    async def test_executemany_tuples_not_dicts(self, uploader_with_mock_pool):
        """
        asyncpg.executemany() acceptă EXCLUSIV tuple-uri, nu dict-uri.
        Verificăm că fiecare element din lista passată e un tuple.
        """
        u, conn = uploader_with_mock_pool
        segments = [make_segment(0), make_segment(1)]

        await u.save_results(TRANSCRIPT_ID, RECORDING_ID, segments, make_metadata())

        _, tuples = conn.executemany.call_args[0]
        for t in tuples:
            assert isinstance(t, tuple), f"Expected tuple, got {type(t)}"

    @pytest.mark.asyncio
    async def test_sql_contains_on_conflict(self, uploader_with_mock_pool):
        """
        INSERT trebuie să conțină ON CONFLICT DO NOTHING.
        Garantează idempotență la restart mid-job.
        """
        u, conn = uploader_with_mock_pool
        segments = [make_segment(0)]

        await u.save_results(TRANSCRIPT_ID, RECORDING_ID, segments, make_metadata())

        insert_sql = conn.executemany.call_args[0][0]
        assert "ON CONFLICT" in insert_sql.upper()

    @pytest.mark.asyncio
    async def test_transcript_updated_to_completed(self, uploader_with_mock_pool):
        """UPDATE pe transcripts trebuie să seteze status='completed'."""
        u, conn = uploader_with_mock_pool
        segments = [make_segment(0)]

        await u.save_results(TRANSCRIPT_ID, RECORDING_ID, segments, make_metadata())

        # Verificăm în toate execute() call-urile că unul setează 'completed'
        all_sqls = [c[0][0] for c in conn.execute.call_args_list]
        assert any("completed" in sql and "transcripts" in sql for sql in all_sqls)

    @pytest.mark.asyncio
    async def test_recording_updated_to_completed(self, uploader_with_mock_pool):
        """UPDATE pe recordings trebuie să seteze status='completed'."""
        u, conn = uploader_with_mock_pool
        segments = [make_segment(0)]

        await u.save_results(TRANSCRIPT_ID, RECORDING_ID, segments, make_metadata())

        all_sqls = [c[0][0] for c in conn.execute.call_args_list]
        assert any("completed" in sql and "recordings" in sql for sql in all_sqls)

    @pytest.mark.asyncio
    async def test_word_count_passed_to_update(self, uploader_with_mock_pool):
        """word_count din metadata trebuie transmis la UPDATE transcripts."""
        u, conn = uploader_with_mock_pool
        segments = [make_segment(0)]
        meta = make_metadata(word_count=123)

        await u.save_results(TRANSCRIPT_ID, RECORDING_ID, segments, meta)

        # Verificăm că 123 apare în parametrii vreunui execute()
        all_params = [c[0][1:] for c in conn.execute.call_args_list]
        flat_params = [p for params in all_params for p in params]
        assert 123 in flat_params

    @pytest.mark.asyncio
    async def test_uses_transaction(self, uploader_with_mock_pool):
        """save_results() trebuie să ruleze totul în aceeași tranzacție."""
        u, conn = uploader_with_mock_pool
        segments = [make_segment(0)]

        await u.save_results(TRANSCRIPT_ID, RECORDING_ID, segments, make_metadata())

        conn.transaction.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_segments_list(self, uploader_with_mock_pool):
        """Nicio transcriere detectată → executemany cu listă goală, fără crash."""
        u, conn = uploader_with_mock_pool

        await u.save_results(TRANSCRIPT_ID, RECORDING_ID, [], make_metadata(word_count=0))

        conn.executemany.assert_called_once()
        _, tuples = conn.executemany.call_args[0]
        assert tuples == []


# ============================================================
# TEST: mark_failed
# ============================================================

class TestMarkFailed:

    @pytest.mark.asyncio
    async def test_updates_transcript_to_failed(self, uploader_with_mock_pool):
        """mark_failed() trebuie să seteze status='failed' pe transcripts."""
        u, conn = uploader_with_mock_pool

        await u.mark_failed(TRANSCRIPT_ID, RECORDING_ID, "Eroare test")

        all_sqls = [c[0][0] for c in conn.execute.call_args_list]
        assert any("failed" in sql and "transcripts" in sql for sql in all_sqls)

    @pytest.mark.asyncio
    async def test_updates_recording_to_failed(self, uploader_with_mock_pool):
        """mark_failed() trebuie să seteze status='failed' pe recordings."""
        u, conn = uploader_with_mock_pool

        await u.mark_failed(TRANSCRIPT_ID, RECORDING_ID, "Eroare test")

        all_sqls = [c[0][0] for c in conn.execute.call_args_list]
        assert any("failed" in sql and "recordings" in sql for sql in all_sqls)

    @pytest.mark.asyncio
    async def test_error_message_saved(self, uploader_with_mock_pool):
        """error_message trebuie transmis ca parametru la UPDATE."""
        u, conn = uploader_with_mock_pool
        error_msg = "FileNotFoundError: /data/processed/missing.mp3"

        await u.mark_failed(TRANSCRIPT_ID, RECORDING_ID, error_msg)

        all_params = [c[0][1:] for c in conn.execute.call_args_list]
        flat_params = [p for params in all_params for p in params]
        assert error_msg in flat_params

    @pytest.mark.asyncio
    async def test_uses_transaction(self, uploader_with_mock_pool):
        """mark_failed() trebuie să ruleze în tranzacție."""
        u, conn = uploader_with_mock_pool

        await u.mark_failed(TRANSCRIPT_ID, RECORDING_ID, "eroare")

        conn.transaction.assert_called_once()
