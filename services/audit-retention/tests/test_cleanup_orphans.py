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


# ── Rularea automată din retenție ─────────────────────────────

from src.cleanup_orphans import purge


def test_purge_deletes_orphans_and_counts_bytes(tmp_path):
    kept = make(tmp_path / "rec_merged.wav")
    orphan = make(tmp_path / "2026" / "10" / "28" / "chunk.webm")

    result = purge(tmp_path, [str(kept)], min_age_hours=24, dry_run=False)

    assert (result.deleted, result.deleted_bytes, result.failed) == (1, 1, 0)
    assert kept.exists() and not orphan.exists()


def test_purge_dry_run_deletes_nothing(tmp_path):
    kept = make(tmp_path / "rec_merged.wav")
    orphan = make(tmp_path / "chunk.webm")

    assert purge(tmp_path, [str(kept)], 24, dry_run=True).deleted == 1
    assert orphan.exists()


def test_purge_skipped_when_database_empty(tmp_path):
    orphan = make(tmp_path / "chunk.webm")

    result = purge(tmp_path, [], 24, dry_run=False)

    assert result.skipped_reason and result.deleted == 0 and orphan.exists()


def test_purge_skipped_when_storage_does_not_match_database(tmp_path):
    """Alt volum montat: niciun fișier al înregistrărilor nu e găsit → nu se șterge nimic."""
    orphan = make(tmp_path / "chunk.webm")

    result = purge(tmp_path, ["/data/processed/altundeva.wav"], 24, dry_run=False)

    assert result.skipped_reason and orphan.exists()
