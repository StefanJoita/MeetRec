# services/audit-retention/tests/test_cleanup_orphans.py
# Curățarea unică a fișierelor audio orfane (BUG-01)

import os
import time

from src.cleanup_orphans import find_orphans

OLD = time.time() - 3 * 24 * 3600


def make(path, age=OLD):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    os.utime(path, (age, age))
    return path


def test_only_unreferenced_old_files_are_orphans(tmp_path):
    day = tmp_path / "2026" / "10" / "28"
    merged = make(tmp_path / "rec1_merged.wav")
    pending_chunk = make(day / "chunk-pending.webm")       # sesiune încă netranscrisă
    mp4 = make(day / "video.mp4")
    playback = make(day / "video.play.mp3")                # copia de redare a unui MP4 existent
    leftover = make(day / "chunk-left.webm")               # bucată rămasă după lipire
    orphan_copy = make(day / "deleted.play.mp3")           # copia unei înregistrări șterse
    fresh = make(day / "just-stored.webm", age=time.time())   # ingest: rândul din DB vine după
    make(tmp_path / "lost+found" / "x")
    make(tmp_path / ".hidden")

    orphans = find_orphans(tmp_path, [str(merged), str(pending_chunk), str(mp4)], min_age_hours=24)

    assert orphans == sorted([leftover, orphan_copy])
    assert all(p.exists() for p in (merged, pending_chunk, mp4, playback, fresh))


def test_empty_storage(tmp_path):
    assert find_orphans(tmp_path, [], min_age_hours=24) == []
