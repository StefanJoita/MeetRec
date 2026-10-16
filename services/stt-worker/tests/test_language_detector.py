# services/stt-worker/tests/test_language_detector.py
# ============================================================
# Teste pentru LanguageDetector
# ============================================================
# whisperx și whisperx.audio sunt importate în interiorul funcțiilor,
# deci le înlocuim în sys.modules. Modelul (FasterWhisperPipeline) e un
# MagicMock: .model = faster_whisper.WhisperModel, .model.model = ctranslate2.
# ============================================================

import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src import language_detector
from src.language_detector import LanguageDetector, _speech_start, choose_language

SR = 16000
N_SAMPLES = SR * 30


def make_model(probabilities: dict) -> MagicMock:
    """Pipeline fals: detect_language întoarce probabilitățile date, sortate descrescător."""
    model = MagicMock()
    model.model.feat_kwargs = {"feature_size": 128}
    ranked = sorted(probabilities.items(), key=lambda kv: -kv[1])
    model.model.model.detect_language.return_value = [[(f"<|{k}|>", v) for k, v in ranked]]
    return model


@pytest.fixture
def whisperx_mock():
    mock = MagicMock()
    mock.load_audio.return_value = np.full(SR * 60, 0.1, dtype=np.float32)
    audio_mock = MagicMock(N_SAMPLES=N_SAMPLES)
    with patch.dict(sys.modules, {"whisperx": mock, "whisperx.audio": audio_mock}), \
         patch.object(language_detector.settings, "whisper_primary_language", "ro"), \
         patch.object(language_detector.settings, "whisper_detect_languages", "ro,en"):
        mock.audio = audio_mock
        yield mock


# ============================================================
# TEST: detect — limba reală, nu cea fixată la încărcarea modelului
# ============================================================

class TestDetect:

    async def test_english_audio_detected_as_english(self, whisperx_mock):
        detector = LanguageDetector(make_model({"en": 0.93, "ro": 0.04}))

        assert await detector.detect("/data/meeting.wav") == "en"

    async def test_romanian_audio_detected_as_romanian(self, whisperx_mock):
        detector = LanguageDetector(make_model({"ro": 0.88, "en": 0.05}))

        assert await detector.detect("/data/meeting.wav") == "ro"

    async def test_does_not_use_transcribe(self, whisperx_mock):
        """transcribe() pe un model încărcat cu language="ro" întoarce mereu "ro"."""
        model = make_model({"en": 0.93})
        await LanguageDetector(model).detect("/data/meeting.wav")

        model.transcribe.assert_not_called()

    async def test_mel_uses_model_feature_size_and_30s(self, whisperx_mock):
        await LanguageDetector(make_model({"ro": 0.9})).detect("/data/meeting.wav")

        audio, = whisperx_mock.audio.log_mel_spectrogram.call_args.args
        kwargs = whisperx_mock.audio.log_mel_spectrogram.call_args.kwargs
        assert len(audio) == N_SAMPLES
        assert kwargs == {"n_mels": 128, "padding": 0}

    async def test_leading_silence_is_skipped(self, whisperx_mock):
        """Detecția rulează pe vorbire, nu pe tăcerea de la începutul ședinței."""
        audio = np.zeros(SR * 60, dtype=np.float32)
        audio[SR * 20:] = 0.1                           # vorbire de la secunda 20
        whisperx_mock.load_audio.return_value = audio

        await LanguageDetector(make_model({"ro": 0.9})).detect("/data/meeting.wav")

        analysed, = whisperx_mock.audio.log_mel_spectrogram.call_args.args
        assert np.all(analysed == 0.1)

    async def test_short_audio_is_padded(self, whisperx_mock):
        whisperx_mock.load_audio.return_value = np.full(SR * 10, 0.1, dtype=np.float32)

        await LanguageDetector(make_model({"ro": 0.9})).detect("/data/short.wav")

        assert whisperx_mock.audio.log_mel_spectrogram.call_args.kwargs["padding"] == SR * 20

    async def test_failure_falls_back_to_primary_language(self, whisperx_mock):
        whisperx_mock.load_audio.side_effect = RuntimeError("ffmpeg")

        assert await LanguageDetector(make_model({"en": 0.9})).detect("/data/x.wav") == "ro"


# ============================================================
# TEST: choose_language
# ============================================================

class TestChooseLanguage:

    @pytest.fixture(autouse=True)
    def _settings(self):
        with patch.object(language_detector.settings, "whisper_primary_language", "ro"), \
             patch.object(language_detector.settings, "whisper_detect_languages", "ro,en"):
            yield

    def test_languages_outside_the_list_are_ignored(self):
        """Pe zgomot Whisper poate „detecta" limbi exotice: alegem doar dintre ro/en."""
        assert choose_language({"nn": 0.6, "en": 0.3, "ro": 0.1}) == "ro"
        assert choose_language({"la": 0.2, "en": 0.7, "ro": 0.1}) == "en"

    def test_uncertain_other_language_keeps_primary(self):
        assert choose_language({"en": 0.45, "ro": 0.40}) == "ro"

    def test_dominant_other_language_wins(self):
        assert choose_language({"en": 0.5, "ro": 0.3}) == "en"

    def test_primary_wins_even_when_uncertain(self):
        assert choose_language({"ro": 0.3, "en": 0.2}) == "ro"

    def test_primary_always_allowed(self):
        with patch.object(language_detector.settings, "whisper_detect_languages", "en"):
            assert choose_language({"ro": 0.8, "en": 0.1}) == "ro"

    def test_empty_probabilities_return_primary(self):
        assert choose_language({}) == "ro"


# ============================================================
# TEST: _speech_start
# ============================================================

class TestSpeechStart:

    def test_starts_at_first_loud_window(self):
        audio = np.zeros(SR * 10, dtype=np.float32)
        audio[SR * 3 + 100:] = 0.05
        assert _speech_start(audio) == SR * 3          # fereastra de 0,5 s care conține începutul

    def test_all_silence_returns_zero(self):
        assert _speech_start(np.zeros(SR * 10, dtype=np.float32)) == 0

    def test_audio_shorter_than_a_window(self):
        assert _speech_start(np.full(100, 0.5, dtype=np.float32)) == 0
