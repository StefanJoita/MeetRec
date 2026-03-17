# services/stt-worker/tests/test_transcriber.py
# ============================================================
# Teste pentru WhisperTranscriber
# ============================================================
# STRATEGIE DE MOCK:
#
# Whisper este importat INSIDE funcțiilor (local import):
#   def _load_model_sync(self):
#       import whisper          ← import local, nu la nivel de modul!
#       return whisper.load_model(...)
#
# PROBLEMA cu patch("src.transcriber.whisper"):
#   Această abordare funcționează DOAR dacă whisper e importat la
#   nivel de modul (top-level). La import local, modulul nu există
#   ca atribut în src.transcriber → AttributeError.
#
# SOLUȚIA: patch.dict("sys.modules", {"whisper": mock})
#   Python verifică sys.modules ÎNAINTE de a executa `import whisper`.
#   Dacă "whisper" există deja acolo, returnează obiectul nostru mock.
#   Funcționează indiferent unde e `import whisper` în cod.
#
# ALTERNATIVA (mai simplă pentru teste transcribe):
#   Setăm direct t._model = mock_model, sărim over load_model().
#   Mai curat, mai rapid, testăm comportamentul dorit direct.
# ============================================================

import math
import sys
import pytest
from unittest.mock import MagicMock, patch

from src.transcriber import WhisperTranscriber, TranscriptSegment


# ── Helpers ───────────────────────────────────────────────────

def make_whisper_segment(
    start=0.0, end=5.0,
    text=" Bună ziua.",
    avg_logprob=-0.15,
    language=None,
) -> dict:
    """Simulează un segment raw din whisper.transcribe()."""
    return {
        "start": start, "end": end,
        "text": text, "avg_logprob": avg_logprob,
        "no_speech_prob": 0.01, "language": language,
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


# ── Fixture: transcriber cu model deja "încărcat" ────────────
# Bypass-uim load_model() (care are nevoie de whisper instalat)
# și setăm direct _model = mock pentru testele de transcribe.

@pytest.fixture
def loaded_transcriber():
    """WhisperTranscriber cu model mock deja setat — fără whisper real."""
    t = WhisperTranscriber()
    t._model = make_mock_model()
    return t


# ============================================================
# TEST: load_model — folosim patch.dict(sys.modules)
# ============================================================

class TestLoadModel:

    async def test_load_model_calls_whisper_load(self):
        """whisper.load_model() trebuie apelat cu modelul și path-ul din settings."""
        mock_whisper = MagicMock()
        mock_whisper.load_model.return_value = MagicMock()

        with patch.dict(sys.modules, {"whisper": mock_whisper}):
            t = WhisperTranscriber()
            await t.load_model()

        mock_whisper.load_model.assert_called_once()
        # Primul argument = numele modelului ("medium" default)
        call_args = mock_whisper.load_model.call_args[0]
        assert call_args[0] == t._model_name

    async def test_load_model_stores_model_reference(self):
        """_model trebuie setat după load_model()."""
        mock_model = MagicMock()
        mock_whisper = MagicMock()
        mock_whisper.load_model.return_value = mock_model

        with patch.dict(sys.modules, {"whisper": mock_whisper}):
            t = WhisperTranscriber()
            assert t._model is None
            await t.load_model()
            assert t._model is mock_model

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
        """transcribe() trebuie să returneze o listă de TranscriptSegment."""
        loaded_transcriber._model.transcribe.return_value = {
            "language": "ro",
            "segments": [
                make_whisper_segment(0.0, 5.0, " Bună ziua."),
                make_whisper_segment(5.0, 10.0, " Azi discutăm."),
            ],
        }
        result = await loaded_transcriber.transcribe("/fake/audio.mp3", "ro")

        assert len(result) == 2
        assert all(isinstance(s, TranscriptSegment) for s in result)

    async def test_segment_indices_are_sequential(self, loaded_transcriber):
        """segment_index trebuie să fie 0, 1, 2, ..."""
        loaded_transcriber._model.transcribe.return_value = {
            "language": "ro",
            "segments": [
                make_whisper_segment(0.0, 5.0),
                make_whisper_segment(5.0, 10.0),
                make_whisper_segment(10.0, 15.0),
            ],
        }
        result = await loaded_transcriber.transcribe("/fake/audio.mp3", "ro")

        assert [s.segment_index for s in result] == [0, 1, 2]

    async def test_text_is_stripped(self, loaded_transcriber):
        """Whisper pune spațiu la început: ' Bună ziua.' → 'Bună ziua.'"""
        loaded_transcriber._model.transcribe.return_value = {
            "language": "ro",
            "segments": [make_whisper_segment(text=" Bună ziua. ")],
        }
        result = await loaded_transcriber.transcribe("/fake/audio.mp3", "ro")

        assert result[0].text == "Bună ziua."

    async def test_timestamps_preserved(self, loaded_transcriber):
        """start_time și end_time trebuie copiate exact din Whisper."""
        loaded_transcriber._model.transcribe.return_value = {
            "language": "ro",
            "segments": [make_whisper_segment(start=12.5, end=17.3)],
        }
        result = await loaded_transcriber.transcribe("/fake/audio.mp3", "ro")

        assert result[0].start_time == 12.5
        assert result[0].end_time == 17.3

    async def test_fp16_false_passed_to_transcribe(self, loaded_transcriber):
        """fp16=False TREBUIE transmis — altfel RuntimeError pe CPU."""
        await loaded_transcriber.transcribe("/fake/audio.mp3", "ro")

        call_kwargs = loaded_transcriber._model.transcribe.call_args[1]
        assert call_kwargs.get("fp16") is False

    async def test_language_hint_passed_when_provided(self, loaded_transcriber):
        """language_hint trebuie transmis la whisper.transcribe()."""
        await loaded_transcriber.transcribe("/fake/audio.mp3", language_hint="en")

        call_kwargs = loaded_transcriber._model.transcribe.call_args[1]
        assert call_kwargs.get("language") == "en"

    async def test_no_language_hint_not_passed(self, loaded_transcriber):
        """Fără language_hint → parametrul 'language' nu trebuie transmis."""
        await loaded_transcriber.transcribe("/fake/audio.mp3", language_hint=None)

        call_kwargs = loaded_transcriber._model.transcribe.call_args[1]
        assert "language" not in call_kwargs

    async def test_empty_audio_returns_empty_list(self, loaded_transcriber):
        """Audio fără vorbire → Whisper returnează [] → returnăm []."""
        loaded_transcriber._model.transcribe.return_value = {
            "language": "ro", "segments": []
        }
        result = await loaded_transcriber.transcribe("/fake/silent.mp3", "ro")

        assert result == []


# ============================================================
# TEST: confidence score conversion
# ============================================================

class TestConfidenceScore:

    async def test_high_confidence_logprob(self, loaded_transcriber):
        """avg_logprob=-0.1 → exp(-0.1) ≈ 0.905"""
        loaded_transcriber._model.transcribe.return_value = {
            "language": "ro",
            "segments": [make_whisper_segment(avg_logprob=-0.1)],
        }
        result = await loaded_transcriber.transcribe("/fake/audio.mp3", "ro")

        expected = round(max(0.0, min(1.0, math.exp(-0.1))), 3)
        assert result[0].confidence == expected

    async def test_low_confidence_logprob(self, loaded_transcriber):
        """avg_logprob=-2.0 → exp(-2.0) ≈ 0.135"""
        loaded_transcriber._model.transcribe.return_value = {
            "language": "ro",
            "segments": [make_whisper_segment(avg_logprob=-2.0)],
        }
        result = await loaded_transcriber.transcribe("/fake/audio.mp3", "ro")

        assert 0.0 < result[0].confidence < 0.5

    async def test_confidence_clamped_to_zero(self, loaded_transcriber):
        """avg_logprob=-100 → exp(-100) ≈ 0 → clamp la 0.0"""
        loaded_transcriber._model.transcribe.return_value = {
            "language": "ro",
            "segments": [make_whisper_segment(avg_logprob=-100.0)],
        }
        result = await loaded_transcriber.transcribe("/fake/audio.mp3", "ro")

        assert result[0].confidence >= 0.0

    async def test_confidence_clamped_to_one(self, loaded_transcriber):
        """avg_logprob=0.1 → exp(0.1) > 1.0 → clamp la 1.0 (DECIMAL(4,3) în DB!)"""
        loaded_transcriber._model.transcribe.return_value = {
            "language": "ro",
            "segments": [make_whisper_segment(avg_logprob=0.1)],
        }
        result = await loaded_transcriber.transcribe("/fake/audio.mp3", "ro")

        assert result[0].confidence <= 1.0

    async def test_confidence_max_3_decimals(self, loaded_transcriber):
        """confidence trebuie rotunjit la max 3 zecimale (DECIMAL(4,3) în DB)."""
        loaded_transcriber._model.transcribe.return_value = {
            "language": "ro",
            "segments": [make_whisper_segment(avg_logprob=-0.33333)],
        }
        result = await loaded_transcriber.transcribe("/fake/audio.mp3", "ro")

        assert result[0].confidence == round(result[0].confidence, 3)
