# services/stt-worker/tests/test_consumer.py
# ============================================================
# Teste pentru JobConsumer
# ============================================================
# Mockăm:
#   - Redis (BRPOP) — nu avem Redis real
#   - WhisperTranscriber
#   - DatabaseUploader
#   - LanguageDetector
#   - PostProcessor (returnează segmentele neschimbate)
#
# Ce testăm:
#   - Pipeline-ul complet e apelat în ordine corectă
#   - Erorile sunt capturate și mark_failed() e apelat
#   - Loop-ul se oprește când _running=False
#   - JSON invalid e ignorat (nu crăpă worker-ul)
#   - _compute_metadata calculează corect word_count și confidence_avg
# ============================================================

import asyncio
import json
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.consumer import JobConsumer
from src.transcriber import TranscriptSegment
from src.uploader import TranscriptMetadata


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
        mocks["uploader"].save_results.side_effect = lambda *a: call_order.append("save_results")

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

        call_args = mocks["uploader"].save_results.call_args[0]
        assert call_args[2] == processed_segs  # al treilea argument = segments


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
# TEST: _poll_once — BRPOP behavior
# ============================================================

class TestPollOnce:

    @pytest.mark.asyncio
    async def test_brpop_timeout_does_not_process(self):
        """
        BRPOP returnează None la timeout (coadă goală).
        Niciun job nu trebuie procesat.
        """
        consumer, mocks = make_mock_consumer()

        mock_redis = AsyncMock()
        mock_redis.brpop = AsyncMock(return_value=None)
        consumer._redis = mock_redis

        await consumer._poll_once()

        mocks["transcriber"].transcribe.assert_not_called()

    @pytest.mark.asyncio
    async def test_valid_job_triggers_process(self):
        """BRPOP returnează un job valid → _process_job() trebuie apelat."""
        consumer, mocks = make_mock_consumer()

        job = make_job()
        mock_redis = AsyncMock()
        mock_redis.brpop = AsyncMock(return_value=("transcription_jobs", json.dumps(job)))
        consumer._redis = mock_redis

        # Mockăm _process_job direct pentru izolare
        consumer._process_job = AsyncMock()

        await consumer._poll_once()

        consumer._process_job.assert_called_once()
        call_args = consumer._process_job.call_args[0][0]
        assert call_args["recording_id"] == RECORDING_ID

    @pytest.mark.asyncio
    async def test_invalid_json_does_not_crash(self):
        """
        JSON invalid → logăm eroarea, nu procesăm, nu crăpăm.
        Workerul trebuie să continue cu jobul următor.
        """
        consumer, mocks = make_mock_consumer()

        mock_redis = AsyncMock()
        mock_redis.brpop = AsyncMock(return_value=("transcription_jobs", "NOT VALID JSON {{{"))
        consumer._redis = mock_redis
        consumer._process_job = AsyncMock()

        # Nu trebuie să arunce excepție
        await consumer._poll_once()

        consumer._process_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_redis_error_does_not_crash(self):
        """
        Eroare la BRPOP (Redis down) → logăm, așteptăm, continuăm.
        """
        consumer, _ = make_mock_consumer()

        mock_redis = AsyncMock()
        mock_redis.brpop = AsyncMock(side_effect=ConnectionError("Redis connection refused"))
        consumer._redis = mock_redis

        with patch("src.consumer.asyncio.sleep", new=AsyncMock()):
            await consumer._poll_once()  # nu trebuie să arunce excepție


# ============================================================
# TEST: stop mechanism
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
        """
        start() loop-ul trebuie să se oprească după ce _running devine False.
        Simulăm: BRPOP timeout → verificare _running=False → ieșire.
        """
        consumer, _ = make_mock_consumer()

        call_count = 0

        async def mock_brpop(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                consumer._running = False  # oprim după primul poll
            return None

        mock_redis = AsyncMock()
        mock_redis.brpop = mock_brpop
        mock_redis.aclose = AsyncMock()

        with patch("src.consumer.aioredis.from_url", return_value=mock_redis):
            await consumer.start()

        assert call_count == 1  # un singur poll, apoi oprire
