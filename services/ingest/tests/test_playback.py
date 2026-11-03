# services/ingest/tests/test_playback.py
# Copia de redare MP3 pentru browser (src/playback.py)

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src import playback
from src.playback import PlaybackPreparer, ffmpeg_command, playback_path, wants_copy


class TestCommand:

    def test_playback_path_next_to_original(self):
        assert playback_path(Path("/data/processed/2026/11/03/abc.mp4")) ==             Path("/data/processed/2026/11/03/abc.play.mp3")

    def test_only_mp4_gets_a_copy(self):
        assert wants_copy(Path("a.mp4")) and wants_copy(Path("a.MP4"))
        assert not wants_copy(Path("a.m4a")) and not wants_copy(Path("a.mp3"))

    def test_audio_only_mono_cbr_mp3_single_thread_low_priority(self, tmp_path):
        cmd = ffmpeg_command(tmp_path / "a.mp4", tmp_path / "a.play.mp3.tmp")

        assert cmd[cmd.index("-map") + 1] == "0:a:0" and "-vn" in cmd
        assert cmd[cmd.index("-c:a") + 1] == "libmp3lame"
        assert cmd[cmd.index("-b:a") + 1] == "64k" and cmd[cmd.index("-ac") + 1] == "1"
        assert cmd[cmd.index("-threads") + 1] == "1"
        if shutil.which("nice"):
            assert cmd[cmd.index("nice") + 1:cmd.index("nice") + 3] == ["-n", "19"]


class TestPreparer:

    @pytest.mark.asyncio
    async def test_schedule_only_mp4(self, tmp_path):
        prep = PlaybackPreparer()
        prep.schedule(tmp_path / "a.mp4")
        prep.schedule(tmp_path / "b.mp3")
        prep.schedule(tmp_path / "c.m4a")

        assert prep._queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_backfill_skips_recordings_that_already_have_a_copy(self, tmp_path):
        done = tmp_path / "done.mp4"
        (tmp_path / "done.play.mp3").write_bytes(b"x")
        database = MagicMock(list_playback_candidates=AsyncMock(
            return_value=[str(done), str(tmp_path / "new.mp4")]))
        prep = PlaybackPreparer()

        await prep.backfill(database)

        database.list_playback_candidates.assert_awaited_once_with(["mp4"])
        assert prep._queue.qsize() == 1
        assert prep._queue.get_nowait().name == "new.mp4"

    @pytest.mark.asyncio
    async def test_backfill_db_error_is_not_fatal(self):
        database = MagicMock(list_playback_candidates=AsyncMock(side_effect=ConnectionError("db")))

        await PlaybackPreparer().backfill(database)     # nu aruncă

    @pytest.mark.asyncio
    async def test_failed_copy_does_not_stop_the_queue(self, monkeypatch, tmp_path):
        calls = []

        async def fake_create(path):
            calls.append(path.name)
            if path.name == "a.mp4":
                raise RuntimeError("ffmpeg")

        monkeypatch.setattr(playback, "create_copy", fake_create)
        prep = PlaybackPreparer()
        prep.start()
        prep.schedule(tmp_path / "a.mp4")
        prep.schedule(tmp_path / "b.mp4")
        await asyncio.wait_for(prep._queue.join(), timeout=5)
        prep.stop()

        assert calls == ["a.mp4", "b.mp4"]


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="necesită ffmpeg")
class TestRealFfmpeg:

    def make(self, path: Path, *extra: str) -> Path:
        subprocess.run(["ffmpeg", "-v", "error", "-y",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
                        "-f", "lavfi", "-i", "color=size=64x64:duration=6",
                        "-c:a", "aac", "-ac", "2", "-c:v", "libx264", "-shortest", *extra, str(path)],
                       check=True, capture_output=True)
        return path

    def probe(self, path: Path) -> dict:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                              "format=format_name,duration:stream=codec_type,codec_name,channels,bit_rate",
                              "-of", "json", str(path)], check=True, capture_output=True, text=True).stdout
        return json.loads(out)

    @pytest.mark.asyncio
    async def test_video_mp4_gets_audio_only_mp3_copy(self, tmp_path):
        src = self.make(tmp_path / "rec.mp4", "-movflags", "frag_keyframe+empty_moov")   # ca un MP4 scris "din mers"

        dst = await playback.create_copy(src)

        assert dst == tmp_path / "rec.play.mp3"
        info = self.probe(dst)
        assert info["format"]["format_name"] == "mp3"
        assert [(s["codec_type"], s["codec_name"], s["channels"]) for s in info["streams"]] == [("audio", "mp3", 1)]
        assert abs(float(info["format"]["duration"]) - 6) < 0.5
        assert not (tmp_path / "rec.play.mp3.tmp").exists()
        assert src.exists()                                    # originalul rămâne neatins

    @pytest.mark.asyncio
    async def test_second_run_does_nothing(self, tmp_path):
        src = self.make(tmp_path / "rec.mp4")

        assert await playback.create_copy(src) is not None
        assert await playback.create_copy(src) is None         # copia există deja

    @pytest.mark.asyncio
    async def test_failed_conversion_leaves_no_files(self, tmp_path):
        src = tmp_path / "corupt.mp4"
        src.write_bytes(b"nu e mp4")

        assert await playback.create_copy(src) is None
        assert sorted(p.name for p in tmp_path.iterdir()) == ["corupt.mp4"]


# ── Integrarea în procesarea fișierelor noi ──────────────────

def make_processor(tmp_path: Path, publish_error: Exception = None):
    from src.processor import FileProcessor
    from src.validator import ValidationResult

    stored = tmp_path / "2026/11/03/uuid.mp4"
    metadata = MagicMock(file_hash_sha256="h", duration_seconds=60, file_size_bytes=1000)
    validator = MagicMock()
    validator.validate.return_value = ValidationResult(is_valid=True, metadata=metadata)
    storage = MagicMock(store_file=MagicMock(return_value=stored))
    database = MagicMock(get_app_setting=AsyncMock(return_value=None),
                         check_duplicate=AsyncMock(return_value=None),
                         create_recording=AsyncMock(return_value="rec-1"),
                         mark_failed_by_id=AsyncMock())
    publisher = MagicMock()
    if publish_error:
        publisher.publish_transcription_job.side_effect = publish_error
    prep = MagicMock()
    order = []
    publisher.publish_transcription_job.side_effect = (
        publish_error or (lambda **kw: order.append("publish")))
    prep.schedule.side_effect = lambda p: order.append(("playback", p))
    proc = FileProcessor(validator=validator, storage=storage, database=database,
                         publisher=publisher, playback=prep)
    return proc, stored, order


@pytest.mark.asyncio
async def test_new_recording_schedules_copy_after_transcription_job(tmp_path):
    proc, stored, order = make_processor(tmp_path)
    f = tmp_path / "Webex.mp4"
    f.write_bytes(b"x")

    assert await proc.process(f) is True

    assert order == ["publish", ("playback", stored)]


@pytest.mark.asyncio
async def test_no_copy_when_publishing_fails(tmp_path):
    proc, _, order = make_processor(tmp_path, publish_error=ConnectionError("redis"))
    f = tmp_path / "Webex.mp4"
    f.write_bytes(b"x")

    assert await proc.process(f) is False

    assert order == []
