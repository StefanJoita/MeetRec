# services/stt-worker/tests/test_transcriber_parallel.py
# ============================================================
# Diarizarea rulează în paralel cu transcrierea (are nevoie doar de audio)
# ============================================================
# whisperx e înlocuit cu un mock; modelele sunt funcții care înregistrează
# în ce fir au rulat și în ce ordine.
# ============================================================

import sys
import threading
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src import transcriber
from src.transcriber import WhisperTranscriber, _whisper_threads

SR = 16000
SEGMENTS = [{"start": 0.0, "end": 2.0, "text": " salut "}]


def make_transcriber(events, *, transcribe_error=None, diarize_error=None, diarize_wait=None):
    """Transcriber cu modele false; `events` primește (etapă, nume fir)."""
    t = WhisperTranscriber()

    def transcribe(audio, **kwargs):
        if diarize_wait is not None:
            # dovada paralelismului: transcrierea așteaptă ca diarizarea să fi pornit
            assert diarize_wait.wait(timeout=5), "diarizarea nu a pornit în paralel"
        events.append(("transcriere", threading.current_thread().name))
        if transcribe_error:
            raise transcribe_error
        return {"segments": list(SEGMENTS), "language": "ro"}

    def diarize(audio, **kwargs):
        events.append(("diarizare", threading.current_thread().name))
        if diarize_wait is not None:
            diarize_wait.set()
        if diarize_error:
            raise diarize_error
        events.append(("diarizare_gata", threading.current_thread().name))
        return "DIARIZE_DF"

    t._model = MagicMock(transcribe=MagicMock(side_effect=transcribe))
    t._diarize_model = MagicMock(side_effect=diarize)
    return t


@pytest.fixture
def whisperx_mock():
    mock = MagicMock()
    mock.load_audio.return_value = np.zeros(SR * 60, dtype=np.float32)   # 1 minut
    mock.assign_word_speakers.side_effect = lambda df, result: {
        **result, "segments": [{**s, "speaker": "SPEAKER_00"} for s in result["segments"]]}
    with patch.dict(sys.modules, {"whisperx": mock}), \
         patch.object(transcriber.settings, "diarization_enabled", True), \
         patch.object(transcriber.settings, "diarization_parallel", True), \
         patch.object(transcriber.settings, "diarization_parallel_max_minutes", 180), \
         patch.object(transcriber, "_set_torch_threads") as torch_threads, \
         patch.object(transcriber, "_cpu_count", return_value=20):
        mock.torch_threads = torch_threads
        yield mock


class TestParallelDiarization:

    def test_diarization_runs_in_other_thread_and_speakers_are_assigned(self, whisperx_mock):
        events = []
        t = make_transcriber(events, diarize_wait=threading.Event())

        segments = t._run_sync("/data/a.wav", "ro")

        threads = dict(events)
        assert threads["diarizare"].startswith("diarize")
        assert threads["transcriere"] != threads["diarizare"]
        whisperx_mock.assign_word_speakers.assert_called_once()
        assert whisperx_mock.assign_word_speakers.call_args.args[0] == "DIARIZE_DF"
        assert [s.speaker_id for s in segments] == ["SPEAKER_00"]

    def test_stage_timings_recorded_for_parallel_run(self, whisperx_mock):
        t = make_transcriber([])

        t._run_sync("/data/a.wav", "ro")

        timings = t.last_timings
        assert timings.diarization_parallel is True
        assert timings.transcription_sec is not None
        assert timings.alignment_sec is None              # fără model de aliniere
        assert timings.diarization_sec is not None

    def test_threads_are_split_and_restored(self, whisperx_mock):
        t = make_transcriber([])

        t._run_sync("/data/a.wav", "ro")

        calls = [c.args[0] for c in whisperx_mock.torch_threads.call_args_list]
        assert 10 in calls                 # jumătate pentru PyTorch cât rulează în paralel
        assert calls[-1] == 20             # la final, din nou toate nucleele
        assert _whisper_threads() == 10    # cealaltă jumătate pentru transcriere

    def test_diarization_failure_keeps_transcript_without_speakers(self, whisperx_mock):
        t = make_transcriber([], diarize_error=RuntimeError("pyannote"))

        segments = t._run_sync("/data/a.wav", "ro")

        assert [s.text for s in segments] == ["salut"]
        assert segments[0].speaker_id is None
        whisperx_mock.assign_word_speakers.assert_not_called()
        assert t.last_timings.diarization_sec is None     # etapa eșuată nu are durată

    def test_transcription_error_waits_for_diarization_then_raises(self, whisperx_mock):
        events = []
        t = make_transcriber(events, transcribe_error=RuntimeError("OOM"), diarize_wait=threading.Event())

        with pytest.raises(RuntimeError, match="OOM"):
            t._run_sync("/data/a.wav", "ro")

        assert "diarizare_gata" in dict(events)           # diarizarea s-a terminat înainte de eroare
        assert whisperx_mock.torch_threads.call_args.args[0] == 20

    def test_long_audio_runs_sequentially(self, whisperx_mock):
        whisperx_mock.load_audio.return_value = np.zeros(SR * 60 * 5, dtype=np.float32)   # 5 minute
        events = []
        t = make_transcriber(events)

        with patch.object(transcriber.settings, "diarization_parallel_max_minutes", 2):
            t._run_sync("/data/a.wav", "ro")

        assert [e[0] for e in events] == ["transcriere", "diarizare", "diarizare_gata"]
        assert events[0][1] == events[1][1]                # același fir, una după alta
        assert t.last_timings.diarization_parallel is False
        assert t.last_timings.diarization_sec is not None

    def test_parallel_disabled_uses_all_cores_sequentially(self, whisperx_mock):
        events = []
        t = make_transcriber(events)

        with patch.object(transcriber.settings, "diarization_parallel", False):
            assert _whisper_threads() == 20
            t._run_sync("/data/a.wav", "ro")

        assert [e[0] for e in events] == ["transcriere", "diarizare", "diarizare_gata"]
        whisperx_mock.torch_threads.assert_not_called()
