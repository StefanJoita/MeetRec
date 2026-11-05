# services/audit-retention/tests/test_fix_session_durations.py
# Corecția unică a duratelor de sesiune (BUG-02): durata se citește din _merged.wav

import wave

from src.fix_session_durations import corrections, wav_duration_seconds


def write_wav(path, seconds: float, rate: int = 16000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))


def row(rec_id, path, duration):
    return {"id": rec_id, "title": f"Ședința {rec_id}", "file_path": str(path), "duration_seconds": duration}


def test_wav_duration_rounds_up(tmp_path):
    write_wav(tmp_path / "a_merged.wav", 389.4)
    assert wav_duration_seconds(tmp_path / "a_merged.wav") == 390


def test_only_wrong_durations_are_corrected(tmp_path):
    write_wav(tmp_path / "ok_merged.wav", 390)
    write_wav(tmp_path / "bad_merged.wav", 390)
    rows = [
        row("ok", tmp_path / "ok_merged.wav", 389),         # diferență de rotunjire: rămâne
        row("bad", tmp_path / "bad_merged.wav", 480),       # bucata de 90 s numărată de două ori
        row("lipsa", tmp_path / "lipsa_merged.wav", 100),   # fișier inexistent: doar raportat
    ]

    fixes, unreadable = corrections(rows)

    assert fixes == [("bad", "Ședința bad", 480, 390)]
    assert unreadable == [str(tmp_path / "lipsa_merged.wav")]
