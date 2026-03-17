# services/stt-worker/tests/test_postprocessor.py
# ============================================================
# Teste pentru PostProcessor
# ============================================================
# Aceste teste NU necesită mock-uri, DB, Redis, sau Whisper.
# PostProcessor este pure Python — cel mai ușor de testat.
# ============================================================

import pytest
from src.postprocessor import PostProcessor
from src.transcriber import TranscriptSegment


def make_segment(text: str, idx: int = 0) -> TranscriptSegment:
    """Helper: creează un segment cu textul dat."""
    return TranscriptSegment(
        segment_index=idx,
        start_time=float(idx * 5),
        end_time=float(idx * 5 + 5),
        text=text,
        confidence=0.9,
        language="ro",
    )


class TestDiacritics:
    """Teste pentru corecția diacriticelor românești."""

    def test_s_cedilla_converted_to_comma_below(self):
        """ş (cedilla, U+015F) → ș (comma-below, U+0219)"""
        pp = PostProcessor()
        result = pp.process([make_segment("şedinţa")])
        assert result[0].text == "ședința"

    def test_uppercase_S_cedilla_converted(self):
        """Ş (cedilla, U+015E) → Ș (comma-below, U+0218)"""
        pp = PostProcessor()
        result = pp.process([make_segment("Şedinţa")])
        assert result[0].text == "Ședința"

    def test_t_cedilla_converted_to_comma_below(self):
        """ţ (cedilla, U+0163) → ț (comma-below, U+021B)"""
        pp = PostProcessor()
        result = pp.process([make_segment("bugeţul")])
        assert result[0].text == "bugețul"

    def test_uppercase_T_cedilla_converted(self):
        """Ţ (cedilla, U+0162) → Ț (comma-below, U+021A)"""
        pp = PostProcessor()
        result = pp.process([make_segment("Ţara")])
        assert result[0].text == "Țara"

    def test_correct_diacritics_unchanged(self):
        """Diacriticele corecte (comma-below) nu trebuie modificate."""
        pp = PostProcessor()
        text = "ședința consiliului local"
        result = pp.process([make_segment(text)])
        assert result[0].text == text

    def test_mixed_text_with_cedilla(self):
        """Text mixt cu mai multe apariții cedilla."""
        pp = PostProcessor()
        result = pp.process([make_segment("şedinţa consiliului şi bugeţul")])
        assert result[0].text == "ședința consiliului și bugețul"

    def test_non_romanian_chars_unchanged(self):
        """Caracterele non-românești nu trebuie atinse."""
        pp = PostProcessor()
        text = "hello world 123 !@#"
        result = pp.process([make_segment(text)])
        assert result[0].text == text


class TestWhitespace:
    """Teste pentru normalizarea spațiilor."""

    def test_leading_space_removed(self):
        """Whisper pune spațiu la începutul segmentelor: ' Bună ziua.'"""
        pp = PostProcessor()
        result = pp.process([make_segment(" Bună ziua.")])
        assert result[0].text == "Bună ziua."

    def test_trailing_space_removed(self):
        pp = PostProcessor()
        result = pp.process([make_segment("Bună ziua.  ")])
        assert result[0].text == "Bună ziua."

    def test_double_space_collapsed(self):
        pp = PostProcessor()
        result = pp.process([make_segment("azi  discutăm")])
        assert result[0].text == "azi discutăm"

    def test_multiple_spaces_collapsed(self):
        pp = PostProcessor()
        result = pp.process([make_segment("azi   discutăm   bugetul")])
        assert result[0].text == "azi discutăm bugetul"

    def test_empty_string_stays_empty(self):
        """Un segment gol rămâne gol."""
        pp = PostProcessor()
        result = pp.process([make_segment("")])
        assert result[0].text == ""

    def test_only_spaces_becomes_empty(self):
        """Un segment cu doar spații devine string gol."""
        pp = PostProcessor()
        result = pp.process([make_segment("   ")])
        assert result[0].text == ""


class TestPreservesOtherFields:
    """PostProcessor trebuie să modifice DOAR textul, nu alte câmpuri."""

    def test_start_end_time_unchanged(self):
        pp = PostProcessor()
        seg = TranscriptSegment(0, 12.5, 17.3, " text ", 0.85, "ro")
        result = pp.process([seg])
        assert result[0].start_time == 12.5
        assert result[0].end_time == 17.3

    def test_confidence_unchanged(self):
        pp = PostProcessor()
        seg = TranscriptSegment(0, 0.0, 5.0, " text ", 0.73, "ro")
        result = pp.process([seg])
        assert result[0].confidence == 0.73

    def test_segment_index_unchanged(self):
        pp = PostProcessor()
        seg = TranscriptSegment(42, 0.0, 5.0, " text ", 0.9, "ro")
        result = pp.process([seg])
        assert result[0].segment_index == 42

    def test_language_unchanged(self):
        pp = PostProcessor()
        seg = TranscriptSegment(0, 0.0, 5.0, " text ", 0.9, "en")
        result = pp.process([seg])
        assert result[0].language == "en"


class TestMultipleSegments:
    """Teste cu liste de segmente."""

    def test_all_segments_processed(self):
        """Toate segmentele din listă trebuie procesate."""
        pp = PostProcessor()
        segments = [
            make_segment(" şedinţa  ", idx=0),
            make_segment("  bugeţul", idx=1),
            make_segment("hotărârea ", idx=2),
        ]
        result = pp.process(segments)
        assert len(result) == 3
        assert result[0].text == "ședința"
        assert result[1].text == "bugețul"
        assert result[2].text == "hotărârea"

    def test_empty_list_returns_empty(self):
        """Lista goală → rezultat gol."""
        pp = PostProcessor()
        result = pp.process([])
        assert result == []

    def test_input_not_modified(self):
        """Procesarea nu modifică lista originală (imutabilitate)."""
        pp = PostProcessor()
        original = make_segment(" şedinţa ")
        original_text = original.text
        pp.process([original])
        # Segmentul original rămâne neschimbat
        assert original.text == original_text
