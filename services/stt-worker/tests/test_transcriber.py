# services/stt-worker/tests/test_transcriber.py
# ============================================================
# Teste pentru WhisperTranscriber
# ============================================================
# Whisper (+ PyTorch) nu e instalat în environment-ul de test.
# Mockăm COMPLET biblioteca whisper cu @patch.
#
# Ce testăm:
#   - Modelul e încărcat cu parametrii corecți
#   - Segmentele Whisper sunt convertite corect (text, timecoding, confidence)
#   - fp16=False e transmis (critic pe CPU)
#   - Confidence score e clampat la [0.0, 1.0]
#   - TranscriptSegment-urile au câmpurile așteptate
# ============================================================

import asyncio
import math
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from src.transcriber import WhisperTranscriber, TranscriptSegment


# ── Helpers ───────────────────────────────────────────────────

def make_whisper_segment(
    start=0.0, end=5.0,
    text=" Bună ziua.",
    avg_logprob=-0.15,
    language=None,
    no_speech_prob=0.01,
) -> dict:
    """Simulează un segment raw din whisper.transcribe()."""
    return {
        "start": start,
        "end": end,
        "text": text,
        "avg_logprob": avg_logprob,
        "no_speech_prob": no_speech_prob,
        "language": language,
    }


def make_mock_model(segments=None, detected_language="ro") -> MagicMock:
    """Creează un model Whisper mock cu segmente predefinite."""
    model = MagicMock()
    model.device = "cpu"
    model.transcribe.return_value = {
        "language": detected_language,
        "segments": segments or [
            make_whisper_segment(0.0, 5.2, " Bună ziua.", -0.15),
            make_whisper_segment(5.2, 10.4, " Azi discutăm bugetul.", -0.20),
        ],
    }
    return model


# ── Fixture ───────────────────────────────────────────────────

@pytest.fixture
def mock_whisper_module():
    """Patch complet al modulului whisper."""
    with patch("src.transcriber.whisper") as mock_w:
        mock_model = make_mock_model()
        mock_w.load_model.return_value = mock_model
        yield mock_w, mock_model


# ============================================================
# TEST: load_model
# ============================================================

class TestLoadModel:

    @pytest.mark.asyncio
    async def test_load_model_calls_whisper_load(self, mock_whisper_module):
        """whisper.load_model() trebuie apelat cu modelul și path-ul din settings."""
        mock_w, _ = mock_whisper_module

        t = WhisperTranscriber()
        await t.load_model()

        mock_w.load_model.assert_called_once()
        call_kwargs = mock_w.load_model.call_args
        # Primul argument = numele modelului (e.g. "medium")
        assert call_kwargs[0][0] == t._model_name

    @pytest.mark.asyncio
    async def test_load_model_stores_model_reference(self, mock_whisper_module):
        """_model trebuie setat după load_model()."""
        _, mock_model = mock_whisper_module

        t = WhisperTranscriber()
        assert t._model is None
        await t.load_model()
        assert t._model is not None

    @pytest.mark.asyncio
    async def test_transcribe_without_load_raises(self):
        """transcribe() fără load_model() trebuie să ridice RuntimeError."""
        t = WhisperTranscriber()
        with pytest.raises(RuntimeError, match="neîncărcat"):
            await t.transcribe("/fake/path.mp3", "ro")


# ============================================================
# TEST: transcribe — segmente și conversie
# ============================================================

class TestTranscribe:

    @pytest.mark.asyncio
    async def test_returns_list_of_segments(self, mock_whisper_module):
        """transcribe() trebuie să returneze o listă de TranscriptSegment."""
        _, mock_model = mock_whisper_module
        mock_model.transcribe.return_value = {
            "language": "ro",
            "segments": [
                make_whisper_segment(0.0, 5.0, " Bună ziua."),
                make_whisper_segment(5.0, 10.0, " Azi discutăm."),
            ],
        }

        t = WhisperTranscriber()
        await t.load_model()
        result = await t.transcribe("/fake/audio.mp3", "ro")

        assert len(result) == 2
        assert all(isinstance(s, TranscriptSegment) for s in result)

    @pytest.mark.asyncio
    async def test_segment_indices_are_sequential(self, mock_whisper_module):
        """segment_index trebuie să fie 0, 1, 2, ..."""
        _, mock_model = mock_whisper_module
        mock_model.transcribe.return_value = {
            "language": "ro",
            "segments": [
                make_whisper_segment(0.0, 5.0),
                make_whisper_segment(5.0, 10.0),
                make_whisper_segment(10.0, 15.0),
            ],
        }

        t = WhisperTranscriber()
        await t.load_model()
        result = await t.transcribe("/fake/audio.mp3", "ro")

        assert [s.segment_index for s in result] == [0, 1, 2]

    @pytest.mark.asyncio
    async def test_text_is_stripped(self, mock_whisper_module):
        """
        Whisper pune spațiu la început: ' Bună ziua.'
        _convert_segment() trebuie să facă strip().
        """
        _, mock_model = mock_whisper_module
        mock_model.transcribe.return_value = {
            "language": "ro",
            "segments": [make_whisper_segment(text=" Bună ziua. ")],
        }

        t = WhisperTranscriber()
        await t.load_model()
        result = await t.transcribe("/fake/audio.mp3", "ro")

        assert result[0].text == "Bună ziua."

    @pytest.mark.asyncio
    async def test_timestamps_preserved(self, mock_whisper_module):
        """start_time și end_time trebuie copiate exact din Whisper."""
        _, mock_model = mock_whisper_module
        mock_model.transcribe.return_value = {
            "language": "ro",
            "segments": [make_whisper_segment(start=12.5, end=17.3)],
        }

        t = WhisperTranscriber()
        await t.load_model()
        result = await t.transcribe("/fake/audio.mp3", "ro")

        assert result[0].start_time == 12.5
        assert result[0].end_time == 17.3

    @pytest.mark.asyncio
    async def test_fp16_false_passed_to_transcribe(self, mock_whisper_module):
        """
        fp16=False TREBUIE transmis — altfel RuntimeError pe CPU.
        Verificăm că whisper.transcribe() e apelat cu fp16=False.
        """
        _, mock_model = mock_whisper_module

        t = WhisperTranscriber()
        await t.load_model()
        await t.transcribe("/fake/audio.mp3", "ro")

        call_kwargs = mock_model.transcribe.call_args[1]
        assert call_kwargs.get("fp16") is False

    @pytest.mark.asyncio
    async def test_language_hint_passed_when_provided(self, mock_whisper_module):
        """language_hint trebuie transmis la whisper.transcribe()."""
        _, mock_model = mock_whisper_module

        t = WhisperTranscriber()
        await t.load_model()
        await t.transcribe("/fake/audio.mp3", language_hint="en")

        call_kwargs = mock_model.transcribe.call_args[1]
        assert call_kwargs.get("language") == "en"

    @pytest.mark.asyncio
    async def test_no_language_hint_not_passed(self, mock_whisper_module):
        """Fără language_hint → parametrul 'language' nu trebuie transmis."""
        _, mock_model = mock_whisper_module

        t = WhisperTranscriber()
        await t.load_model()
        await t.transcribe("/fake/audio.mp3", language_hint=None)

        call_kwargs = mock_model.transcribe.call_args[1]
        assert "language" not in call_kwargs

    @pytest.mark.asyncio
    async def test_empty_audio_returns_empty_list(self, mock_whisper_module):
        """Audio fără vorbire → Whisper returnează [] → returnăm [] de segmente."""
        _, mock_model = mock_whisper_module
        mock_model.transcribe.return_value = {"language": "ro", "segments": []}

        t = WhisperTranscriber()
        await t.load_model()
        result = await t.transcribe("/fake/silent.mp3", "ro")

        assert result == []


# ============================================================
# TEST: confidence score conversion
# ============================================================

class TestConfidenceScore:
    """
    avg_logprob (Whisper) → confidence (0.0 - 1.0)
    Formula: confidence = exp(avg_logprob), clampat la [0, 1]
    """

    @pytest.mark.asyncio
    async def test_high_confidence_logprob(self, mock_whisper_module):
        """avg_logprob=-0.1 → exp(-0.1) ≈ 0.905 → confidence ≈ 0.905"""
        _, mock_model = mock_whisper_module
        mock_model.transcribe.return_value = {
            "language": "ro",
            "segments": [make_whisper_segment(avg_logprob=-0.1)],
        }

        t = WhisperTranscriber()
        await t.load_model()
        result = await t.transcribe("/fake/audio.mp3", "ro")

        expected = round(max(0.0, min(1.0, math.exp(-0.1))), 3)
        assert result[0].confidence == expected

    @pytest.mark.asyncio
    async def test_low_confidence_logprob(self, mock_whisper_module):
        """avg_logprob=-2.0 → exp(-2.0) ≈ 0.135 → confidence ≈ 0.135"""
        _, mock_model = mock_whisper_module
        mock_model.transcribe.return_value = {
            "language": "ro",
            "segments": [make_whisper_segment(avg_logprob=-2.0)],
        }

        t = WhisperTranscriber()
        await t.load_model()
        result = await t.transcribe("/fake/audio.mp3", "ro")

        assert 0.0 < result[0].confidence < 0.5

    @pytest.mark.asyncio
    async def test_confidence_clamped_to_zero(self, mock_whisper_module):
        """avg_logprob=-100 → exp(-100) ≈ 0 → clamp la 0.0"""
        _, mock_model = mock_whisper_module
        mock_model.transcribe.return_value = {
            "language": "ro",
            "segments": [make_whisper_segment(avg_logprob=-100.0)],
        }

        t = WhisperTranscriber()
        await t.load_model()
        result = await t.transcribe("/fake/audio.mp3", "ro")

        assert result[0].confidence >= 0.0

    @pytest.mark.asyncio
    async def test_confidence_clamped_to_one(self, mock_whisper_module):
        """avg_logprob=0.1 → exp(0.1) > 1.0 → clamp la 1.0 (DECIMAL(4,3) în DB!)"""
        _, mock_model = mock_whisper_module
        mock_model.transcribe.return_value = {
            "language": "ro",
            "segments": [make_whisper_segment(avg_logprob=0.1)],
        }

        t = WhisperTranscriber()
        await t.load_model()
        result = await t.transcribe("/fake/audio.mp3", "ro")

        assert result[0].confidence <= 1.0

    @pytest.mark.asyncio
    async def test_confidence_max_3_decimals(self, mock_whisper_module):
        """confidence trebuie rotunjit la max 3 zecimale (DECIMAL(4,3) în DB)."""
        _, mock_model = mock_whisper_module
        mock_model.transcribe.return_value = {
            "language": "ro",
            "segments": [make_whisper_segment(avg_logprob=-0.33333)],
        }

        t = WhisperTranscriber()
        await t.load_model()
        result = await t.transcribe("/fake/audio.mp3", "ro")

        # Max 3 zecimale
        assert result[0].confidence == round(result[0].confidence, 3)
