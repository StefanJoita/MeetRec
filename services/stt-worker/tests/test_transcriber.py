# services/stt-worker/tests/test_transcriber.py
# ============================================================
# Teste pentru WhisperTranscriber (WhisperX)
# ============================================================
# STRATEGIE DE MOCK:
#
# whisperx este importat INSIDE funcțiilor (import local), deci îl
# înlocuim în sys.modules: patch.dict("sys.modules", {"whisperx": mock}).
# Python găsește mock-ul înainte de a executa `import whisperx`.
#
# Pentru transcriere setăm direct t._model (modelul faster-whisper) și
# lăsăm alinierea/diarizarea dezactivate: testăm conversia segmentelor.
# Firele, progresul și diarizarea paralelă au teste separate:
#   test_transcriber_threads_progress.py, test_transcriber_parallel.py
# ============================================================

import math
import sys
import threading
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src import transcriber
from src.cancellation import JobCancelled
from src.transcriber import TranscriptSegment, WhisperTranscriber


# ── Helpers ───────────────────────────────────────────────────

def make_segment(start=0.0, end=5.0, text=" Bună ziua.", avg_logprob=-0.15, **extra) -> dict:
    """Simulează un segment din FasterWhisperPipeline.transcribe()."""
    return {"start": start, "end": end, "text": text, "avg_logprob": avg_logprob, **extra}


@pytest.fixture
def whisperx_mock():
    """whisperx fals: load_audio întoarce 10 s de liniște; diarizarea e oprită."""
    mock = MagicMock()
    mock.load_audio.return_value = np.zeros(16000 * 10, dtype=np.float32)
    mock.load_align_model.return_value = (MagicMock(), {"language": "ro"})
    with patch.dict(sys.modules, {"whisperx": mock}), \
         patch.object(transcriber.settings, "diarization_enabled", False):
        yield mock


@pytest.fixture
def loaded_transcriber(whisperx_mock):
    """WhisperTranscriber cu model mock deja setat, fără aliniere și diarizare."""
    t = WhisperTranscriber()
    t._model = MagicMock()
    t._align_models = {"ro": None, "en": None}   # aliniere oprită
    t._model.transcribe.return_value = {
        "language": "ro",
        "segments": [make_segment(0.0, 5.2, " Bună ziua."), make_segment(5.2, 10.4, " Azi discutăm bugetul.")],
    }
    return t


def returns(t, *segments, language="ro"):
    t._model.transcribe.return_value = {"language": language, "segments": list(segments)}


# ============================================================
# TEST: load_model
# ============================================================

class TestLoadModel:

    async def test_load_model_calls_whisperx_with_settings(self, whisperx_mock):
        """whisperx.load_model() primește modelul, compute_type și limba din settings."""
        t = WhisperTranscriber()
        await t.load_model()

        whisperx_mock.load_model.assert_called_once()
        args, kwargs = whisperx_mock.load_model.call_args
        assert args[0] == transcriber.settings.whisper_model
        assert kwargs["device"] == "cpu"
        assert kwargs["compute_type"] == transcriber.settings.whisper_compute_type
        assert kwargs["language"] == transcriber.settings.whisper_primary_language

    async def test_load_model_blocks_repetition_loops(self, whisperx_mock):
        """Modelul primește no_repeat_ngram_size (oprește frazele repetate în buclă)."""
        await WhisperTranscriber().load_model()

        kwargs = whisperx_mock.load_model.call_args.kwargs
        assert kwargs["asr_options"] == {
            "no_repeat_ngram_size": transcriber.settings.whisper_no_repeat_ngram_size}
        assert transcriber.settings.whisper_no_repeat_ngram_size == 10

    async def test_load_model_stores_model_reference(self, whisperx_mock):
        """_model trebuie setat după load_model()."""
        t = WhisperTranscriber()
        assert t._model is None
        await t.load_model()
        assert t._model is whisperx_mock.load_model.return_value

    async def test_missing_align_model_is_not_fatal(self, whisperx_mock):
        """Fără model de aliniere pentru limbă, transcrierea continuă fără el."""
        whisperx_mock.load_align_model.side_effect = ValueError("no align model")
        t = WhisperTranscriber()
        await t.load_model()
        assert t._model is not None
        assert t._align_models == {"ro": None}

    async def test_load_model_loads_only_primary_align_model(self, whisperx_mock):
        """La startup se încarcă doar alinierea pentru limba principală."""
        await WhisperTranscriber().load_model()

        whisperx_mock.load_align_model.assert_called_once_with(
            language_code=transcriber.settings.whisper_primary_language, device="cpu")

    async def test_transcribe_without_load_raises(self):
        """transcribe() fără load_model() trebuie să ridice RuntimeError."""
        t = WhisperTranscriber()
        with pytest.raises(RuntimeError, match="neîncărcat"):
            await t.transcribe("/fake/path.mp3", "ro")


# ============================================================
# TEST: transcribe — segmente și conversie
# ============================================================

class TestTranscribe:

    async def test_returns_list_of_segments(self, loaded_transcriber):
        result = await loaded_transcriber.transcribe("/fake/audio.mp3", "ro")

        assert len(result) == 2
        assert all(isinstance(s, TranscriptSegment) for s in result)

    async def test_segment_indices_are_sequential(self, loaded_transcriber):
        returns(loaded_transcriber, make_segment(0, 5), make_segment(5, 10), make_segment(10, 15))
        result = await loaded_transcriber.transcribe("/fake/audio.mp3", "ro")

        assert [s.segment_index for s in result] == [0, 1, 2]

    async def test_text_is_stripped(self, loaded_transcriber):
        """Whisper pune spațiu la început: ' Bună ziua. ' → 'Bună ziua.'"""
        returns(loaded_transcriber, make_segment(text=" Bună ziua. "))
        result = await loaded_transcriber.transcribe("/fake/audio.mp3", "ro")

        assert result[0].text == "Bună ziua."

    async def test_timestamps_preserved(self, loaded_transcriber):
        returns(loaded_transcriber, make_segment(start=12.5, end=17.3))
        result = await loaded_transcriber.transcribe("/fake/audio.mp3", "ro")

        assert (result[0].start_time, result[0].end_time) == (12.5, 17.3)

    async def test_language_hint_passed_when_provided(self, loaded_transcriber):
        await loaded_transcriber.transcribe("/fake/audio.mp3", language_hint="en")

        assert loaded_transcriber._model.transcribe.call_args.kwargs["language"] == "en"
        # fără task explicit, WhisperX 3.8.6 eșuează pe altă limbă decât cea de la încărcare
        assert loaded_transcriber._model.transcribe.call_args.kwargs["task"] == "transcribe"

    async def test_no_language_hint_uses_primary_language(self, loaded_transcriber):
        """Fără language_hint → limba principală din settings (implicit ro)."""
        await loaded_transcriber.transcribe("/fake/audio.mp3", language_hint=None)

        assert (loaded_transcriber._model.transcribe.call_args.kwargs["language"]
                == transcriber.settings.whisper_primary_language)

    async def test_detected_language_set_on_segments(self, loaded_transcriber):
        returns(loaded_transcriber, make_segment(), language="en")
        result = await loaded_transcriber.transcribe("/fake/audio.mp3", "en")

        assert result[0].language == "en"

    async def test_empty_audio_returns_empty_list(self, loaded_transcriber):
        """Audio fără vorbire → niciun segment."""
        returns(loaded_transcriber)
        result = await loaded_transcriber.transcribe("/fake/silent.mp3", "ro")

        assert result == []

    async def test_speaker_id_none_without_diarization(self, loaded_transcriber):
        result = await loaded_transcriber.transcribe("/fake/audio.mp3", "ro")

        assert all(s.speaker_id is None for s in result)

    async def test_alignment_failure_keeps_unaligned_segments(self, loaded_transcriber, whisperx_mock):
        """O eroare la aliniere nu pierde transcrierea."""
        loaded_transcriber._align_models["ro"] = (MagicMock(), {"language": "ro"})
        whisperx_mock.align.side_effect = RuntimeError("wav2vec2")
        result = await loaded_transcriber.transcribe("/fake/audio.mp3", "ro")

        assert [s.text for s in result] == ["Bună ziua.", "Azi discutăm bugetul."]


# ============================================================
# TEST: anulare și progres
# ============================================================

class TestCancelAndProgress:

    def _transcribe_with_progress(self, t, percents):
        """Modelul fals apelează callback-ul de progres, ca WhisperX după fiecare lot."""
        def transcribe(audio, **kwargs):
            for p in percents:
                kwargs["progress_callback"](p)
            return {"language": "ro", "segments": [make_segment()]}
        t._model.transcribe.side_effect = transcribe

    async def test_progress_recorded_per_stage(self, loaded_transcriber):
        self._transcribe_with_progress(loaded_transcriber, [50.0, 100.0])

        await loaded_transcriber.transcribe("/fake/a.mp3", "ro")

        assert loaded_transcriber.progress == {"transcriere": 100}

    async def test_cancel_stops_at_next_batch(self, loaded_transcriber):
        cancel = threading.Event()
        seen = []

        def transcribe(audio, **kwargs):
            for p in (25.0, 50.0, 75.0):
                seen.append(p)
                if p == 50.0:
                    cancel.set()                      # anulare în timpul lotului 2
                kwargs["progress_callback"](p)
            return {"language": "ro", "segments": []}
        loaded_transcriber._model.transcribe.side_effect = transcribe

        with pytest.raises(JobCancelled):
            await loaded_transcriber.transcribe("/fake/a.mp3", "ro", cancel=cancel)

        assert seen == [25.0, 50.0]

    async def test_cancel_before_alignment_skips_it(self, loaded_transcriber, whisperx_mock):
        cancel = threading.Event()
        loaded_transcriber._align_models["ro"] = (MagicMock(), {"language": "ro"})

        def transcribe(audio, **kwargs):
            cancel.set()                              # anulare după ultimul lot
            return {"language": "ro", "segments": [make_segment()]}
        loaded_transcriber._model.transcribe.side_effect = transcribe

        with pytest.raises(JobCancelled):
            await loaded_transcriber.transcribe("/fake/a.mp3", "ro", cancel=cancel)

        whisperx_mock.align.assert_not_called()

    async def test_cancel_during_alignment_is_not_swallowed(self, loaded_transcriber, whisperx_mock):
        """O eroare de aliniere e ignorată; anularea nu."""
        cancel = threading.Event()
        loaded_transcriber._align_models["ro"] = (MagicMock(), {"language": "ro"})

        def align(segments, *a, progress_callback=None, **kw):
            cancel.set()
            progress_callback(10.0)
        whisperx_mock.align.side_effect = align

        with pytest.raises(JobCancelled):
            await loaded_transcriber.transcribe("/fake/a.mp3", "ro", cancel=cancel)

    async def test_cancel_during_diarization_is_not_swallowed(self, loaded_transcriber):
        cancel = threading.Event()

        def diarize(audio, progress_callback=None, **kw):
            cancel.set()
            progress_callback(10.0)
        loaded_transcriber._diarize_model = MagicMock(side_effect=diarize)

        with pytest.raises(JobCancelled):
            await loaded_transcriber.transcribe("/fake/a.mp3", "ro", cancel=cancel)


# ============================================================
# TEST: modelul de aliniere pe limbă
# ============================================================

class TestAlignModelPerLanguage:

    async def test_other_language_loads_its_align_model_once(self, loaded_transcriber, whisperx_mock):
        """Prima înregistrare în engleză încarcă alinierea engleză; următoarele o refolosesc."""
        del loaded_transcriber._align_models["en"]
        en_model = (MagicMock(), {"language": "en"})
        whisperx_mock.load_align_model.return_value = en_model
        whisperx_mock.align.side_effect = lambda segments, *a, **kw: {"segments": segments}
        returns(loaded_transcriber, make_segment(text=" Good morning."), language="en")

        await loaded_transcriber.transcribe("/fake/a.mp3", "en")
        await loaded_transcriber.transcribe("/fake/b.mp3", "en")

        whisperx_mock.load_align_model.assert_called_once_with(language_code="en", device="cpu")
        assert whisperx_mock.align.call_count == 2
        assert whisperx_mock.align.call_args.args[1:3] == en_model

    async def test_primary_language_keeps_its_align_model(self, loaded_transcriber, whisperx_mock):
        """O înregistrare în română folosește în continuare modelul românesc."""
        ro_model = (MagicMock(), {"language": "ro"})
        loaded_transcriber._align_models["ro"] = ro_model
        whisperx_mock.align.side_effect = lambda segments, *a, **kw: {"segments": segments}

        await loaded_transcriber.transcribe("/fake/a.mp3", "ro")

        whisperx_mock.load_align_model.assert_not_called()
        assert whisperx_mock.align.call_args.args[1:3] == ro_model

    async def test_unavailable_align_model_is_not_retried(self, loaded_transcriber, whisperx_mock):
        """Model lipsă (ex. imagine offline fără el) → transcriere fără aliniere, fără reîncercări."""
        del loaded_transcriber._align_models["en"]
        whisperx_mock.load_align_model.side_effect = OSError("offline")
        returns(loaded_transcriber, make_segment(text=" Good morning."), language="en")

        first = await loaded_transcriber.transcribe("/fake/a.mp3", "en")
        await loaded_transcriber.transcribe("/fake/b.mp3", "en")

        assert [s.text for s in first] == ["Good morning."]
        whisperx_mock.load_align_model.assert_called_once()
        whisperx_mock.align.assert_not_called()


# ============================================================
# TEST: confidence score
# ============================================================

class TestConfidenceScore:

    async def test_high_confidence_logprob(self, loaded_transcriber):
        """avg_logprob=-0.1 → exp(-0.1) ≈ 0.905"""
        returns(loaded_transcriber, make_segment(avg_logprob=-0.1))
        result = await loaded_transcriber.transcribe("/fake/audio.mp3", "ro")

        assert result[0].confidence == round(math.exp(-0.1), 3)

    async def test_low_confidence_logprob(self, loaded_transcriber):
        returns(loaded_transcriber, make_segment(avg_logprob=-2.0))
        result = await loaded_transcriber.transcribe("/fake/audio.mp3", "ro")

        assert 0.0 < result[0].confidence < 0.5

    async def test_confidence_clamped_to_zero(self, loaded_transcriber):
        returns(loaded_transcriber, make_segment(avg_logprob=-100.0))
        result = await loaded_transcriber.transcribe("/fake/audio.mp3", "ro")

        assert result[0].confidence == 0.0

    async def test_confidence_clamped_to_one(self, loaded_transcriber):
        """avg_logprob=0.1 → exp(0.1) > 1.0 → 1.0 (DECIMAL(4,3) în DB)."""
        returns(loaded_transcriber, make_segment(avg_logprob=0.1))
        result = await loaded_transcriber.transcribe("/fake/audio.mp3", "ro")

        assert result[0].confidence == 1.0

    async def test_confidence_max_3_decimals(self, loaded_transcriber):
        returns(loaded_transcriber, make_segment(avg_logprob=-0.33333))
        result = await loaded_transcriber.transcribe("/fake/audio.mp3", "ro")

        assert result[0].confidence == round(result[0].confidence, 3)

    async def test_aligned_segment_uses_word_scores(self, loaded_transcriber):
        """După aliniere segmentul nu mai are avg_logprob → media scorurilor cuvintelor."""
        returns(loaded_transcriber, {"start": 0, "end": 2, "text": " Da da",
                                     "words": [{"word": "Da", "score": 0.8}, {"word": "da", "score": 0.6}]})
        result = await loaded_transcriber.transcribe("/fake/audio.mp3", "ro")

        assert result[0].confidence == 0.7

    async def test_no_score_defaults_to_half(self, loaded_transcriber):
        returns(loaded_transcriber, {"start": 0, "end": 2, "text": " ?"})
        result = await loaded_transcriber.transcribe("/fake/audio.mp3", "ro")

        assert result[0].confidence == 0.5
