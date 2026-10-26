# services/ingest/tests/test_validator.py
# ============================================================
# Teste pentru AudioValidator
# ============================================================
# pytest 101:
#   - Fiecare funcție care începe cu "test_" e un test automat
#   - assert X == Y: dacă e fals, testul pică cu eroare clară
#   - fixture: date pregătite refolosibile între teste
#   - mock: înlocuim dependențe reale cu "false" controlate
# ============================================================

import hashlib
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.validator import AudioValidator, ValidationResult


# ============================================================
# FIXTURES — Date de test refolosibile
# ============================================================

@pytest.fixture
def validator():
    """Creează un validator proaspăt pentru fiecare test."""
    return AudioValidator()


@pytest.fixture
def temp_audio_file(tmp_path: Path):
    """
    Creează un fișier audio fake pentru teste.
    tmp_path = director temporar creat de pytest (sters dupa test).
    """
    audio_file = tmp_path / "test_sedinta.mp3"
    # Scriem câțiva bytes care simulează un MP3 (header magic bytes)
    audio_file.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 1000)
    return audio_file


@pytest.fixture
def large_audio_file(tmp_path: Path):
    """Fișier care depășește limita de dimensiune."""
    audio_file = tmp_path / "huge_file.mp3"
    # Scriem 600MB de zero-uri
    audio_file.write_bytes(b"\x00" * (600 * 1024 * 1024))
    return audio_file


# ============================================================
# TESTE
# ============================================================

class TestExtensionValidation:
    """Teste pentru validarea extensiei fișierului."""

    def test_valid_mp3_extension(self, validator, tmp_path):
        """MP3 trebuie acceptat."""
        f = tmp_path / "test.mp3"
        f.write_bytes(b"\x00" * 100)
        # Mockuim mutagen să nu încarce fișierul real
        with patch("src.validator.mutagen.File") as mock_mutagen:
            mock_info = MagicMock()
            mock_info.length = 60.0  # 60 secunde
            mock_info.sample_rate = 44100
            mock_info.channels = 2
            mock_info.bitrate = 128000
            mock_mutagen.return_value.info = mock_info
            result = validator.validate(f)
        # Nu ne interesează dacă trece complet, ci dacă nu cade la extensie
        assert result.error_code != "INVALID_FORMAT"

    def test_pdf_extension_rejected(self, validator, tmp_path):
        """PDF nu trebuie acceptat ca audio."""
        f = tmp_path / "document.pdf"
        f.write_bytes(b"%PDF-1.4")
        result = validator.validate(f)
        assert result.is_valid is False
        assert result.error_code == "INVALID_FORMAT"

    def test_uppercase_extension_accepted(self, validator, tmp_path):
        """Extensiile uppercase (.MP3) trebuie normalizate și acceptate."""
        f = tmp_path / "test.WAV"
        f.write_bytes(b"\x00" * 100)
        with patch("src.validator.mutagen.File") as mock_mutagen:
            mock_info = MagicMock()
            mock_info.length = 60.0
            mock_info.sample_rate = 44100
            mock_info.channels = 1
            mock_info.bitrate = None
            mock_mutagen.return_value.info = mock_info
            result = validator.validate(f)
        assert result.error_code != "INVALID_FORMAT"


class TestFileSizeValidation:
    """Teste pentru validarea dimensiunii."""

    def test_empty_file_rejected(self, validator, tmp_path):
        """Fișier gol (0 bytes) nu trebuie acceptat."""
        f = tmp_path / "empty.mp3"
        f.write_bytes(b"")  # gol
        result = validator.validate(f)
        assert result.is_valid is False
        assert result.error_code == "FILE_EMPTY"

    def test_file_too_large_rejected(self, validator, large_audio_file):
        """Fișier > 500MB trebuie respins."""
        result = validator.validate(large_audio_file)
        assert result.is_valid is False
        assert result.error_code == "FILE_TOO_LARGE"
        assert "500" in result.error_message  # mesajul conține limita

    def test_normal_file_size_accepted(self, validator, tmp_path):
        """Un fișier de 10MB trebuie să treacă de verificarea dimensiunii."""
        f = tmp_path / "normal.mp3"
        f.write_bytes(b"\x00" * (10 * 1024 * 1024))  # 10MB
        with patch("src.validator.mutagen.File") as mock_mutagen:
            mock_info = MagicMock()
            mock_info.length = 300.0  # 5 minute
            mock_info.sample_rate = 44100
            mock_info.channels = 2
            mock_info.bitrate = 128000
            mock_mutagen.return_value.info = mock_info
            result = validator.validate(f)
        assert result.error_code != "FILE_TOO_LARGE"


class TestSHA256:
    """Teste pentru calculul hash-ului."""

    def test_hash_is_consistent(self, validator, tmp_path):
        """Același fișier trebuie să producă același hash."""
        f = tmp_path / "consistent.mp3"
        content = b"test audio content 12345"
        f.write_bytes(content)

        hash1 = validator._calculate_sha256(f)
        hash2 = validator._calculate_sha256(f)

        assert hash1 == hash2

    def test_different_files_different_hash(self, validator, tmp_path):
        """Fișiere diferite trebuie să aibă hash-uri diferite."""
        f1 = tmp_path / "file1.mp3"
        f2 = tmp_path / "file2.mp3"
        f1.write_bytes(b"content one")
        f2.write_bytes(b"content two")

        assert validator._calculate_sha256(f1) != validator._calculate_sha256(f2)

    def test_hash_length_is_64(self, validator, tmp_path):
        """SHA256 trebuie să fie exact 64 caractere hexadecimale."""
        f = tmp_path / "test.mp3"
        f.write_bytes(b"some content")

        result_hash = validator._calculate_sha256(f)
        assert len(result_hash) == 64
        assert all(c in "0123456789abcdef" for c in result_hash)


class TestFileNotFound:
    """Teste pentru fișiere inexistente."""

    def test_missing_file_rejected(self, validator):
        """Un fișier care nu există trebuie respins clar."""
        result = validator.validate(Path("/tmp/nonexistent_12345.mp3"))
        assert result.is_valid is False
        assert result.error_code == "FILE_NOT_FOUND"

    def test_directory_rejected(self, validator, tmp_path):
        """Un director (nu fișier) trebuie respins."""
        result = validator.validate(tmp_path)  # tmp_path e un director
        assert result.is_valid is False
        assert result.error_code == "NOT_A_FILE"


class TestValidationResult:
    """Teste pentru structura ValidationResult."""

    def test_reject_creates_correct_result(self, validator):
        """_reject trebuie să creeze un ValidationResult negativ corect."""
        result = validator._reject("TEST_CODE", "Test message")
        assert result.is_valid is False
        assert result.error_code == "TEST_CODE"
        assert result.error_message == "Test message"
        assert result.metadata is None  # metadata e None la eșec

class TestFfprobeFallback:
    """
    M4A de la reportofonul telefoanelor Samsung (brand 3gp4): mutagen le
    recunoaște ca MP4, dar raportează durata 0. Durata se citește cu ffprobe.
    """

    @staticmethod
    def _m4a(tmp_path: Path) -> Path:
        f = tmp_path / "Voce 261006_113235.m4a"
        f.write_bytes(b"\x00\x00\x00\x18ftyp3gp4" + b"\x00" * 1000)
        return f

    @staticmethod
    def _mutagen_with_length(length):
        audio = MagicMock()
        audio.info.length = length
        audio.info.sample_rate = 0
        audio.info.channels = 0
        audio.info.bitrate = 0
        return audio

    @staticmethod
    def _ffprobe_output(payload: dict):
        import json
        return MagicMock(stdout=json.dumps(payload))

    def test_zero_duration_from_mutagen_uses_ffprobe(self, validator, tmp_path):
        f = self._m4a(tmp_path)
        probe = {"streams": [{"sample_rate": "48000", "channels": 1}],
                 "format": {"duration": "4346.876083", "bit_rate": "130512"}}
        with patch("src.validator.mutagen.File", return_value=self._mutagen_with_length(0.0)), \
             patch("src.validator.subprocess.run", return_value=self._ffprobe_output(probe)) as run:
            result = validator.validate(f)

        assert result.is_valid
        assert result.metadata.duration_seconds == 4346
        assert result.metadata.sample_rate_hz == 48000
        assert result.metadata.channels == 1
        assert result.metadata.bitrate_kbps == 130
        assert run.call_args.args[0][0] == "ffprobe"

    def test_file_unknown_to_mutagen_is_accepted_if_ffprobe_finds_audio(self, validator, tmp_path):
        f = self._m4a(tmp_path)
        probe = {"streams": [{"sample_rate": "44100", "channels": 2, "duration": "61.5"}], "format": {}}
        with patch("src.validator.mutagen.File", return_value=None), \
             patch("src.validator.subprocess.run", return_value=self._ffprobe_output(probe)):
            result = validator.validate(f)

        assert result.is_valid
        assert result.metadata.duration_seconds == 61

    def test_no_audio_stream_is_still_rejected(self, validator, tmp_path):
        f = self._m4a(tmp_path)
        with patch("src.validator.mutagen.File", return_value=self._mutagen_with_length(0.0)), \
             patch("src.validator.subprocess.run", return_value=self._ffprobe_output({"streams": [], "format": {}})):
            result = validator.validate(f)

        assert not result.is_valid
        assert result.error_code == "INVALID_DURATION"

    def test_unreadable_by_both_is_rejected(self, validator, tmp_path):
        import subprocess
        f = self._m4a(tmp_path)
        with patch("src.validator.mutagen.File", return_value=None), \
             patch("src.validator.subprocess.run", side_effect=subprocess.CalledProcessError(1, "ffprobe")):
            result = validator.validate(f)

        assert not result.is_valid
        assert result.error_code == "UNREADABLE_AUDIO"

    def test_ffprobe_not_called_when_mutagen_has_duration(self, validator, tmp_path):
        f = self._m4a(tmp_path)
        with patch("src.validator.mutagen.File", return_value=self._mutagen_with_length(120.0)), \
             patch("src.validator.subprocess.run") as run:
            result = validator.validate(f)

        assert result.is_valid and result.metadata.duration_seconds == 120
        run.assert_not_called()
