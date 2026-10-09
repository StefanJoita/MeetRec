# services/stt-worker/tests/test_consumer.py
# ============================================================
# Teste pentru JobConsumer
# ============================================================
# Mockăm:
#   - Redis — fakeredis (BLMOVE / LREM / MULTI cu semantică reală)
#   - WhisperTranscriber
#   - DatabaseUploader (pentru idempotență: un DB minim în memorie)
#   - LanguageDetector
#   - PostProcessor (returnează segmentele neschimbate)
#
# Ce testăm:
#   - Pipeline-ul complet e apelat în ordine corectă
#   - Erorile sunt capturate și mark_failed() e apelat
#   - Coada fiabilă: jobul stă în processing cât rulează, e scos după succes/eșec
#   - Recuperarea la pornire, limita MAX_JOB_ATTEMPTS, oprirea la SIGTERM
#   - Reprocesarea nu dublează segmentele
#   - _compute_metadata calculează corect word_count și confidence_avg
# ============================================================

import asyncio
import json
import uuid
import fakeredis
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.consumer import JobConsumer
from src.transcriber import TranscriptSegment
from src.uploader import DatabaseUploader, TranscriptMetadata


# ── Helpers ───────────────────────────────────────────────────

RECORDING_ID  = str(uuid.uuid4())
TRANSCRIPT_ID = str(uuid.uuid4())


def make_job(**kwargs) -> dict:
    """Simulează un job JSON din Redis (publicat de ingest)."""
    defaults = {
        "recording_id": RECORDING_ID,
        "file_path": "/data/processed/2024/03/15/test.mp3",
        "audio_format": "mp3",
        "duration_seconds": 3600,
        "language_hint": "ro",
    }
    defaults.update(kwargs)
    return defaults


def make_segment(idx: int = 0, text: str = "Bună ziua consiliu") -> TranscriptSegment:
    return TranscriptSegment(
        segment_index=idx,
        start_time=float(idx * 5),
        end_time=float(idx * 5 + 4.9),
        text=text,
        confidence=0.85,
        language="ro",
    )


# ── Fixture: mock consumer ────────────────────────────────────

def make_mock_consumer() -> tuple[JobConsumer, dict]:
    """
    Creează un JobConsumer cu toate dependențele mock-uite.
    Returnează (consumer, mocks_dict) pentru acces în teste.
    """
    transcriber = AsyncMock()
    transcriber._model_name = "medium"
    transcriber.transcribe = AsyncMock(return_value=[make_segment(0), make_segment(1)])

    uploader = AsyncMock()
    uploader.get_transcript_id = AsyncMock(return_value=TRANSCRIPT_ID)
    uploader.mark_processing = AsyncMock()
    uploader.save_results = AsyncMock()
    uploader.mark_failed = AsyncMock()

    detector = AsyncMock()
    detector.detect = AsyncMock(return_value="ro")

    postprocessor = MagicMock()
    postprocessor.process = MagicMock(side_effect=lambda segs: segs)  # pass-through

    consumer = JobConsumer(
        transcriber=transcriber,
        uploader=uploader,
        detector=detector,
        postprocessor=postprocessor,
    )

    mocks = {
        "transcriber": transcriber,
        "uploader": uploader,
        "detector": detector,
        "postprocessor": postprocessor,
    }
    return consumer, mocks


# ============================================================
# TEST: _process_job — pipeline complet
# ============================================================

class TestProcessJob:

    @pytest.mark.asyncio
    async def test_full_pipeline_called_in_order(self):
        """
        Verificăm că toți pașii pipeline-ului sunt apelați.
        Ordinea: get_transcript_id → mark_processing → detect → transcribe → process → save_results
        """
        consumer, mocks = make_mock_consumer()
        call_order = []

        mocks["uploader"].get_transcript_id.side_effect = lambda *a: call_order.append("get_id") or TRANSCRIPT_ID
        mocks["uploader"].mark_processing.side_effect = lambda *a: call_order.append("mark_processing")
        mocks["detector"].detect.side_effect = lambda *a: call_order.append("detect") or "ro"
        mocks["transcriber"].transcribe.side_effect = lambda *a, **kw: call_order.append("transcribe") or [make_segment()]
        mocks["postprocessor"].process.side_effect = lambda s: call_order.append("postprocess") or s
        mocks["uploader"].save_results.side_effect = lambda *a, **kw: call_order.append("save_results")

        await consumer._process_job(make_job())

        assert call_order == [
            "get_id", "mark_processing", "detect", "transcribe", "postprocess", "save_results"
        ]

    @pytest.mark.asyncio
    async def test_mark_failed_called_on_exception(self):
        """
        Dacă transcrierea aruncă o excepție, mark_failed() trebuie apelat.
        Workerul NU trebuie să propageze excepția.
        """
        consumer, mocks = make_mock_consumer()
        mocks["transcriber"].transcribe.side_effect = RuntimeError("CUDA out of memory")

        # Nu trebuie să arunce excepție
        await consumer._process_job(make_job())

        mocks["uploader"].mark_failed.assert_called_once()
        call_args = mocks["uploader"].mark_failed.call_args[0]
        assert "CUDA out of memory" in call_args[2]

    @pytest.mark.asyncio
    async def test_save_results_not_called_on_exception(self):
        """Dacă transcrierea eșuează, save_results() NU trebuie apelat."""
        consumer, mocks = make_mock_consumer()
        mocks["transcriber"].transcribe.side_effect = FileNotFoundError("/data/missing.mp3")

        await consumer._process_job(make_job())

        mocks["uploader"].save_results.assert_not_called()

    @pytest.mark.asyncio
    async def test_language_hint_passed_to_transcribe(self):
        """language detectată trebuie transmisă la transcriber.transcribe()."""
        consumer, mocks = make_mock_consumer()
        mocks["detector"].detect.return_value = "en"

        await consumer._process_job(make_job(language_hint="en"))

        call_args = mocks["transcriber"].transcribe.call_args
        assert call_args[0][1] == "en" or call_args[1].get("language_hint") == "en"

    @pytest.mark.asyncio
    async def test_missing_transcript_id_skips_job(self):
        """
        Dacă get_transcript_id() returnează None (inconsistență DB),
        jobul e sărit fără crash și fără mark_failed().
        """
        consumer, mocks = make_mock_consumer()
        mocks["uploader"].get_transcript_id.return_value = None

        await consumer._process_job(make_job())

        mocks["uploader"].mark_processing.assert_not_called()
        mocks["transcriber"].transcribe.assert_not_called()

    @pytest.mark.asyncio
    async def test_postprocessor_receives_transcriber_output(self):
        """PostProcessor trebuie să primească segmentele de la transcriber."""
        consumer, mocks = make_mock_consumer()
        expected_segments = [make_segment(0), make_segment(1)]
        mocks["transcriber"].transcribe.return_value = expected_segments

        await consumer._process_job(make_job())

        mocks["postprocessor"].process.assert_called_once_with(expected_segments)

    @pytest.mark.asyncio
    async def test_save_results_receives_processed_segments(self):
        """save_results() trebuie să primească segmentele DUPĂ postprocessor."""
        consumer, mocks = make_mock_consumer()
        raw_segs = [make_segment(0, "şedinţa")]
        processed_segs = [make_segment(0, "ședința")]  # diacritice fixate

        mocks["transcriber"].transcribe.return_value = raw_segs
        # IMPORTANT: side_effect are prioritate față de return_value în MagicMock.
        # Trebuie să anulăm side_effect înainte de a seta return_value.
        mocks["postprocessor"].process.side_effect = None
        mocks["postprocessor"].process.return_value = processed_segs

        await consumer._process_job(make_job())

        call_kwargs = mocks["uploader"].save_results.call_args.kwargs
        assert call_kwargs["segments"] == processed_segs


# ============================================================
# TEST: _compute_metadata
# ============================================================

class TestComputeMetadata:

    def test_word_count_correct(self):
        consumer, _ = make_mock_consumer()
        segments = [
            make_segment(0, "Bună ziua"),     # 2 cuvinte
            make_segment(1, "Azi discutăm"),  # 2 cuvinte
        ]
        meta = consumer._compute_metadata(segments, "ro", "whisper-medium", 60)
        assert meta.word_count == 4

    def test_confidence_avg_correct(self):
        consumer, _ = make_mock_consumer()
        segments = [
            TranscriptSegment(0, 0.0, 5.0, "text", 0.8, "ro"),
            TranscriptSegment(1, 5.0, 10.0, "text", 0.6, "ro"),
        ]
        meta = consumer._compute_metadata(segments, "ro", "whisper-medium", 60)
        assert meta.confidence_avg == pytest.approx(0.7, abs=0.001)

    def test_confidence_avg_3_decimals(self):
        consumer, _ = make_mock_consumer()
        segments = [
            TranscriptSegment(0, 0.0, 5.0, "text", 1/3, "ro"),
        ]
        meta = consumer._compute_metadata(segments, "ro", "whisper-medium", 60)
        assert meta.confidence_avg == round(meta.confidence_avg, 3)

    def test_empty_segments_returns_zero_counts(self):
        consumer, _ = make_mock_consumer()
        meta = consumer._compute_metadata([], "ro", "whisper-medium", 30)
        assert meta.word_count == 0
        assert meta.confidence_avg == 0.0

    def test_language_preserved(self):
        consumer, _ = make_mock_consumer()
        meta = consumer._compute_metadata([], "en", "whisper-medium", 30)
        assert meta.language == "en"

    def test_model_name_preserved(self):
        consumer, _ = make_mock_consumer()
        meta = consumer._compute_metadata([], "ro", "whisper-large-v3", 30)
        assert meta.model_used == "whisper-large-v3"

    def test_processing_time_preserved(self):
        consumer, _ = make_mock_consumer()
        meta = consumer._compute_metadata([], "ro", "whisper-medium", 999)
        assert meta.processing_time_sec == 999


# ============================================================
# Coadă fiabilă — Redis simulat cu fakeredis (semantică reală
# pentru BLMOVE / LREM / MULTI)
# ============================================================

QUEUE = "transcription_jobs"


def make_reliable_consumer(server: fakeredis.FakeServer = None):
    """Consumer cu dependențe mock și Redis fakeredis (worker_id fix)."""
    consumer, mocks = make_mock_consumer()
    consumer._queue = QUEUE
    consumer._worker_id = "worker-a"
    consumer._processing_list = f"{QUEUE}:processing:worker-a"
    server = server or fakeredis.FakeServer()
    consumer._redis = fakeredis.FakeAsyncRedis(server=server, decode_responses=True)
    return consumer, mocks, consumer._redis


async def processing(redis) -> list:
    return await redis.lrange(f"{QUEUE}:processing:worker-a", 0, -1)


async def queue_contents(redis) -> list:
    return await redis.lrange(QUEUE, 0, -1)


# ============================================================
# TEST: _poll_once — BLMOVE + confirmare
# ============================================================

class TestPollOnce:

    @pytest.mark.asyncio
    async def test_timeout_does_not_process(self):
        """BLMOVE returnează None la timeout (coadă goală) → nimic de procesat."""
        consumer, mocks = make_mock_consumer()
        mock_redis = AsyncMock()
        mock_redis.blmove = AsyncMock(return_value=None)
        consumer._redis = mock_redis

        await consumer._poll_once()

        mocks["transcriber"].transcribe.assert_not_called()
        mock_redis.lrem.assert_not_called()

    @pytest.mark.asyncio
    async def test_blmove_moves_from_queue_tail_to_processing_head(self):
        consumer, _, redis = make_reliable_consumer()
        consumer._process_job = AsyncMock()
        mock_blmove = AsyncMock(return_value=None)
        consumer._redis.blmove = mock_blmove

        await consumer._poll_once()

        mock_blmove.assert_awaited_once_with(
            QUEUE, f"{QUEUE}:processing:worker-a", timeout=30, src="RIGHT", dest="LEFT"
        )

    @pytest.mark.asyncio
    async def test_job_stays_in_processing_while_running(self):
        consumer, _, redis = make_reliable_consumer()
        raw = json.dumps(make_job())
        await redis.lpush(QUEUE, raw)
        seen = {}

        async def _process(job):
            seen["queue"] = await queue_contents(redis)
            seen["processing"] = await processing(redis)

        consumer._process_job = _process
        await consumer._poll_once()

        assert seen == {"queue": [], "processing": [raw]}
        assert await processing(redis) == []          # confirmat după succes

    @pytest.mark.asyncio
    async def test_job_removed_from_processing_after_mark_failed(self):
        consumer, mocks, redis = make_reliable_consumer()
        mocks["transcriber"].transcribe.side_effect = RuntimeError("model crash")
        await redis.lpush(QUEUE, json.dumps(make_job()))

        await consumer._poll_once()

        mocks["uploader"].mark_failed.assert_awaited_once()
        assert await processing(redis) == []
        assert await queue_contents(redis) == []

    @pytest.mark.asyncio
    async def test_unhandled_error_is_acked_and_does_not_crash(self):
        """mark_failed eșuează (DB căzut) → jobul e confirmat, worker-ul continuă."""
        consumer, mocks, redis = make_reliable_consumer()
        mocks["transcriber"].transcribe.side_effect = RuntimeError("model crash")
        mocks["uploader"].mark_failed.side_effect = ConnectionError("DB down")
        await redis.lpush(QUEUE, json.dumps(make_job()))

        await consumer._poll_once()

        assert await processing(redis) == []

    @pytest.mark.asyncio
    async def test_oldest_job_is_consumed_first(self):
        consumer, _, redis = make_reliable_consumer()
        await redis.lpush(QUEUE, json.dumps(make_job(recording_id="vechi")))
        await redis.lpush(QUEUE, json.dumps(make_job(recording_id="nou")))
        consumer._process_job = AsyncMock()

        await consumer._poll_once()

        assert consumer._process_job.call_args[0][0]["recording_id"] == "vechi"

    @pytest.mark.asyncio
    async def test_invalid_json_does_not_crash_and_is_acked(self):
        consumer, _, redis = make_reliable_consumer()
        await redis.lpush(QUEUE, "NOT VALID JSON {{{")
        consumer._process_job = AsyncMock()

        await consumer._poll_once()

        consumer._process_job.assert_not_called()
        assert await processing(redis) == []

    @pytest.mark.asyncio
    async def test_redis_error_does_not_crash(self):
        """Eroare la BLMOVE (Redis down) → logăm, așteptăm, continuăm."""
        consumer, _ = make_mock_consumer()
        mock_redis = AsyncMock()
        mock_redis.blmove = AsyncMock(side_effect=ConnectionError("Redis connection refused"))
        consumer._redis = mock_redis

        with patch("src.consumer.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            await consumer._poll_once()  # nu trebuie să arunce excepție

        mock_sleep.assert_awaited_once_with(5)


# ============================================================
# TEST: recuperarea la pornire
# ============================================================

class TestRecoveryOnStartup:

    @pytest.mark.asyncio
    async def test_leftover_job_is_requeued_on_consume_side(self):
        consumer, _, redis = make_reliable_consumer()
        consumer._running = True
        leftover = make_job(recording_id="ramas")
        await redis.lpush(f"{QUEUE}:processing:worker-a", json.dumps(leftover))
        await redis.lpush(QUEUE, json.dumps(make_job(recording_id="in-asteptare")))

        await consumer._recover_processing()

        assert await processing(redis) == []
        # RPUSH → capătul din dreapta, de unde consumă BLMOVE: reluat primul
        tail = json.loads((await queue_contents(redis))[-1])
        assert tail == {**leftover, "attempts": 1}

    @pytest.mark.asyncio
    async def test_start_recovers_before_consuming(self):
        server = fakeredis.FakeServer()
        consumer, _, redis = make_reliable_consumer(server)
        await redis.lpush(QUEUE, json.dumps(make_job(recording_id="in-asteptare")))
        await redis.lpush(f"{QUEUE}:processing:worker-a", json.dumps(make_job(recording_id="ramas")))
        processed = []

        async def _process(job):
            processed.append(job)
            consumer._running = False

        consumer._process_job = _process
        client = fakeredis.FakeAsyncRedis(server=server, decode_responses=True)
        with patch("src.consumer.aioredis.from_url", return_value=client):
            await consumer.start()

        assert [j["recording_id"] for j in processed] == ["ramas"]
        assert processed[0]["attempts"] == 1
        assert await processing(redis) == []

    @pytest.mark.asyncio
    async def test_multiple_leftovers_keep_order(self):
        consumer, _, redis = make_reliable_consumer()
        consumer._running = True
        for rid in ("primul", "al-doilea"):      # LPUSH, ca BLMOVE ... LEFT
            await redis.lpush(f"{QUEUE}:processing:worker-a", json.dumps(make_job(recording_id=rid)))

        await consumer._recover_processing()

        consumed_order = [json.loads(j)["recording_id"] for j in reversed(await queue_contents(redis))]
        assert consumed_order == ["primul", "al-doilea"]

    @pytest.mark.asyncio
    async def test_max_attempts_marks_failed_and_is_not_requeued(self):
        consumer, mocks, redis = make_reliable_consumer()
        consumer._running = True
        await redis.lpush(f"{QUEUE}:processing:worker-a", json.dumps(make_job(attempts=1)))

        with patch("src.consumer.settings.max_job_attempts", 2):
            await consumer._recover_processing()

        mocks["uploader"].mark_failed.assert_awaited_once_with(
            TRANSCRIPT_ID,
            RECORDING_ID,
            "Procesul de transcriere s-a oprit de 2 ori pe acest fișier (posibil memorie insuficientă)",
        )
        assert await processing(redis) == []
        assert await queue_contents(redis) == []

    @pytest.mark.asyncio
    async def test_crash_loop_ends_after_max_attempts(self):
        """Simulăm două căderi consecutive pe același job: prima → reluat, a doua → failed."""
        consumer, mocks, redis = make_reliable_consumer()
        consumer._running = True
        await redis.lpush(QUEUE, json.dumps(make_job()))

        with patch("src.consumer.settings.max_job_attempts", 2):
            for _ in range(2):
                # "Procesul moare" după BLMOVE: jobul rămâne în processing
                await redis.blmove(QUEUE, f"{QUEUE}:processing:worker-a", 1, "RIGHT", "LEFT")
                await consumer._recover_processing()

        assert mocks["uploader"].mark_failed.await_count == 1
        assert await queue_contents(redis) == []
        assert await processing(redis) == []

    @pytest.mark.asyncio
    async def test_db_error_when_abandoning_keeps_job_in_processing(self):
        consumer, mocks, redis = make_reliable_consumer()
        consumer._running = True
        raw = json.dumps(make_job(attempts=5))
        await redis.lpush(f"{QUEUE}:processing:worker-a", raw)
        mocks["uploader"].get_transcript_id.side_effect = ConnectionError("DB down")

        await consumer._recover_processing()

        assert await processing(redis) == [raw]       # reîncercat la următoarea pornire

    @pytest.mark.asyncio
    async def test_other_workers_processing_lists_are_not_touched(self):
        consumer, _, redis = make_reliable_consumer()
        consumer._running = True
        other = json.dumps(make_job(recording_id="al-altui-worker"))
        await redis.lpush(f"{QUEUE}:processing:worker-b", other)

        await consumer._recover_processing()

        assert await redis.lrange(f"{QUEUE}:processing:worker-b", 0, -1) == [other]
        assert await queue_contents(redis) == []


# ============================================================
# TEST: oprire (SIGTERM) — jobul curent rămâne în processing
# ============================================================

class TestStop:

    def test_stop_sets_running_false(self):
        """stop() trebuie să seteze _running=False."""
        consumer, _ = make_mock_consumer()
        consumer._running = True

        consumer.stop()

        assert consumer._running is False

    @pytest.mark.asyncio
    async def test_loop_exits_when_running_false(self):
        """start() se oprește după ce _running devine False."""
        consumer, _ = make_mock_consumer()
        call_count = 0

        async def mock_blmove(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            consumer._running = False  # oprim după primul poll
            return None

        mock_redis = AsyncMock()
        mock_redis.lrange = AsyncMock(return_value=[])
        mock_redis.blmove = mock_blmove
        mock_redis.aclose = AsyncMock()

        with patch("src.consumer.aioredis.from_url", return_value=mock_redis):
            await consumer.start()

        assert call_count == 1
        mock_redis.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cancel_during_job_keeps_it_in_processing_as_interrupted(self):
        consumer, _, redis = make_reliable_consumer()
        await redis.lpush(QUEUE, json.dumps(make_job()))
        started = asyncio.Event()

        async def _long_transcription(job):
            started.set()
            await asyncio.Event().wait()            # "transcriere de o oră"

        consumer._process_job = _long_transcription
        task = asyncio.create_task(consumer._poll_once())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        [raw] = await processing(redis)
        assert json.loads(raw) == {**make_job(), "interrupted": True}

        # La pornire: reluat fără să se numere ca încercare eșuată
        consumer._running = True
        await consumer._recover_processing()
        [requeued] = await queue_contents(redis)
        assert json.loads(requeued) == {**make_job(), "attempts": 0}


# ============================================================
# TEST: idempotență la reprocesare
# ============================================================

class TestIdempotentReprocessing:

    @pytest.mark.asyncio
    async def test_completed_transcript_is_skipped_and_acked(self):
        consumer, mocks, redis = make_reliable_consumer()
        mocks["uploader"].get_transcript_status = AsyncMock(return_value="completed")
        await redis.lpush(QUEUE, json.dumps(make_job()))

        await consumer._poll_once()

        mocks["uploader"].mark_processing.assert_not_called()
        mocks["transcriber"].transcribe.assert_not_called()
        mocks["uploader"].save_results.assert_not_called()
        assert await processing(redis) == []

    @pytest.mark.asyncio
    async def test_completed_session_transcript_is_skipped(self):
        consumer, mocks, _ = make_reliable_consumer()
        mocks["uploader"].get_transcript_status = AsyncMock(return_value="completed")

        await consumer._process_job({"recording_id": RECORDING_ID, "session_mode": True})

        mocks["uploader"].mark_processing.assert_not_called()
        mocks["uploader"].save_session_results.assert_not_called()

    @pytest.mark.asyncio
    async def test_completed_audio_segment_job_is_skipped(self):
        consumer, mocks, _ = make_reliable_consumer()
        mocks["uploader"].get_audio_segment_status = AsyncMock(return_value="completed")

        await consumer._process_job(make_job(segment_id="seg-1", segment_index=1))

        mocks["transcriber"].transcribe.assert_not_called()
        mocks["uploader"].save_results.assert_not_called()

    @pytest.mark.asyncio
    async def test_pending_transcript_is_processed(self):
        consumer, mocks, _ = make_reliable_consumer()
        mocks["uploader"].get_transcript_status = AsyncMock(return_value="processing")

        await consumer._process_job(make_job())

        mocks["uploader"].save_results.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_save_results_twice_does_not_duplicate_segments(self):
        uploader, db = make_uploader_with_fake_db()

        await uploader.save_results(TRANSCRIPT_ID, RECORDING_ID, [make_segment(i) for i in range(3)], make_metadata())
        # Reluare după crash: Whisper poate segmenta ușor diferit
        await uploader.save_results(TRANSCRIPT_ID, RECORDING_ID, [make_segment(i, "alt text") for i in range(2)], make_metadata())

        assert sorted(db.segments) == [(TRANSCRIPT_ID, 0), (TRANSCRIPT_ID, 1)]
        assert {row["text"] for row in db.segments.values()} == {"alt text"}

    @pytest.mark.asyncio
    async def test_save_session_results_twice_does_not_duplicate_segments(self):
        uploader, db = make_uploader_with_fake_db()

        await uploader.save_session_results(TRANSCRIPT_ID, RECORDING_ID, [make_segment(i) for i in range(4)], make_metadata())
        await uploader.save_session_results(TRANSCRIPT_ID, RECORDING_ID, [make_segment(i, "reluat") for i in range(3)], make_metadata())

        assert sorted(idx for _, idx in db.segments) == [0, 1, 2]
        assert {row["text"] for row in db.segments.values()} == {"reluat"}

    @pytest.mark.asyncio
    async def test_multipart_segment_job_does_not_delete_other_parts(self):
        """Job pe un segment audio suplimentar: segmentele celorlalte părți rămân."""
        uploader, db = make_uploader_with_fake_db(audio_segments={RECORDING_ID})
        await uploader.save_results(TRANSCRIPT_ID, RECORDING_ID, [make_segment(i) for i in range(3)], make_metadata())

        await uploader.save_results(
            TRANSCRIPT_ID, RECORDING_ID, [make_segment(0), make_segment(1)], make_metadata(),
            index_offset=3, time_offset_sec=300.0, segment_id="seg-1",
        )

        assert sorted(idx for _, idx in db.segments) == [0, 1, 2, 3, 4]


# ── DB în memorie pentru testele de idempotență ───────────────

class FakeSegmentsDB:
    """Interpretează doar instrucțiunile din save_results / save_session_results."""

    def __init__(self, audio_segments: set):
        self.segments: dict = {}                 # (transcript_id, segment_index) → rând
        self.audio_segments = audio_segments     # recording_id-uri cu recording_audio_segments

    async def execute(self, sql, *args):
        if "DELETE FROM transcript_segments" not in sql:
            return
        transcript_id = args[0]
        if "segment_index >= $2" in sql:
            min_index, recording_id = args[1], args[2]
            if recording_id in self.audio_segments:      # NOT EXISTS (...) e fals
                return
        else:
            min_index = 0
        for key in [k for k in self.segments if k[0] == transcript_id and k[1] >= min_index]:
            del self.segments[key]

    async def executemany(self, sql, rows):
        assert "ON CONFLICT (transcript_id, segment_index) DO NOTHING" in sql
        for _id, transcript_id, idx, start, end, text, *_ in rows:
            self.segments.setdefault((transcript_id, idx), {"text": text, "start": start})

    async def fetchval(self, sql, *args):
        return 0

    async def fetchrow(self, sql, *args):
        return {"word_count": 1, "confidence_avg": 0.9, "total": 100}

    def transaction(self):
        tx = AsyncMock()
        tx.__aenter__ = AsyncMock(return_value=None)
        tx.__aexit__ = AsyncMock(return_value=False)
        return tx


def make_uploader_with_fake_db(audio_segments: set = frozenset()):
    db = FakeSegmentsDB(set(audio_segments))
    acq = AsyncMock()
    acq.__aenter__ = AsyncMock(return_value=db)
    acq.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acq)
    uploader = DatabaseUploader()
    uploader._pool = pool
    return uploader, db


def make_metadata() -> TranscriptMetadata:
    return TranscriptMetadata(
        word_count=3, confidence_avg=0.9, processing_time_sec=10,
        language="ro", model_used="whisper-large-v3",
    )

