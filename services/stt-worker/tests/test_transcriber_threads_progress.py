# services/stt-worker/tests/test_transcriber_threads_progress.py
# ============================================================
# Teste pentru firele CPU ale faster-whisper și logarea progresului
# ============================================================
# WhisperX folosește implicit threads=4, indiferent câte nuclee are
# serverul; workerul trebuie să ceară explicit toate nucleele.
# ============================================================

import sys
from unittest.mock import MagicMock, patch

from src import transcriber
from src.transcriber import WhisperTranscriber, _progress_logger, _whisper_threads


class TestWhisperThreads:

    def test_default_uses_all_container_cores(self):
        with patch.object(transcriber.settings, "whisper_threads", 0), \
             patch.object(transcriber.os, "sched_getaffinity", return_value=set(range(20)), create=True):
            assert _whisper_threads() == 20

    def test_explicit_value_wins(self):
        with patch.object(transcriber.settings, "whisper_threads", 6), \
             patch.object(transcriber.os, "sched_getaffinity", return_value=set(range(20)), create=True):
            assert _whisper_threads() == 6

    def test_fallback_to_cpu_count(self):
        with patch.object(transcriber.settings, "whisper_threads", 0), \
             patch.object(transcriber.os, "sched_getaffinity", side_effect=AttributeError, create=True), \
             patch.object(transcriber.os, "cpu_count", return_value=12):
            assert _whisper_threads() == 12

    def test_load_model_passes_threads(self):
        mock_whisperx = MagicMock()
        with patch.dict(sys.modules, {"whisperx": mock_whisperx}), \
             patch.object(transcriber.settings, "whisper_threads", 0), \
             patch.object(transcriber.settings, "diarization_enabled", False), \
             patch.object(transcriber.os, "sched_getaffinity", return_value=set(range(20)), create=True):
            WhisperTranscriber()._load_sync()

        assert mock_whisperx.load_model.call_args.kwargs["threads"] == 20


class TestProgressLogger:

    def _reported(self, values, step=10):
        with patch.object(transcriber, "logger") as mock_logger:
            report = _progress_logger("/data/a.wav", "transcriere", step=step)
            for v in values:
                report(v)
        return [c.kwargs["percent"] for c in mock_logger.info.call_args_list]

    def test_logs_once_per_step(self):
        values = [i * 100 / 37 for i in range(1, 38)]   # 37 segmente → 37 apeluri
        logged = self._reported(values)
        assert len(logged) == 10                        # 10%, 20%, ..., 100%
        assert [p // 10 for p in logged] == list(range(1, 11))

    def test_every_mark_logged_at_most_once(self):
        logged = self._reported([5, 12, 14, 19, 25, 100])
        assert logged == [12, 25, 100]

    def test_large_jump_logs_once(self):
        assert self._reported([100]) == [100]

    def test_stage_and_file_in_log(self):
        with patch.object(transcriber, "logger") as mock_logger:
            _progress_logger("/data/a.wav", "aliniere")(50)
        kwargs = mock_logger.info.call_args.kwargs
        assert mock_logger.info.call_args.args == ("transcription_progress",)
        assert kwargs["stage"] == "aliniere" and kwargs["file"] == "/data/a.wav"
