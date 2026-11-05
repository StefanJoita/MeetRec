import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.watcher import AudioFileHandler, InboxWatcher


class DummyProcessor:
    async def process(self, file_path: Path) -> bool:
        return True


def test_sidecar_is_ignored_as_primary_input(tmp_path):
    loop = asyncio.new_event_loop()
    handler = AudioFileHandler(processor=DummyProcessor(), event_loop=loop)
    sidecar = tmp_path / "meeting.wav.meetrec-meta.json"
    sidecar.write_text('{"title":"sedinta"}', encoding="utf-8")

    with patch("src.watcher.asyncio.run_coroutine_threadsafe") as run_threadsafe:
        handler._handle_new_file(sidecar)

    assert run_threadsafe.call_count == 0
    assert str(sidecar) not in handler._processing
    loop.close()


def test_audio_file_is_scheduled_for_processing(tmp_path):
    loop = asyncio.new_event_loop()
    handler = AudioFileHandler(processor=DummyProcessor(), event_loop=loop)
    audio = tmp_path / "meeting.wav"
    audio.write_bytes(b"abc")

    done_future = MagicMock()
    done_future.result.return_value = True
    fake_future = MagicMock()

    with patch.object(handler, "_wait_for_file_stable", return_value=None), patch(
        "src.watcher.asyncio.run_coroutine_threadsafe", return_value=fake_future
    ) as run_threadsafe:
        handler._handle_new_file(audio)

    assert run_threadsafe.call_count == 1
    fake_future.add_done_callback.assert_called_once()

    callback = fake_future.add_done_callback.call_args[0][0]
    callback(done_future)
    assert str(audio) not in handler._processing
    loop.close()


def test_process_existing_files_skips_sidecar(monkeypatch, tmp_path):
    loop = asyncio.new_event_loop()
    audio = tmp_path / "meeting.wav"
    sidecar = tmp_path / "meeting.wav.meetrec-meta.json"
    audio.write_bytes(b"abc")
    sidecar.write_text('{"title":"sedinta"}', encoding="utf-8")

    processor = DummyProcessor()
    watcher = InboxWatcher(processor=processor, event_loop=loop)
    handler = AudioFileHandler(processor=processor, event_loop=loop)
    handler._handle_new_file = MagicMock()

    monkeypatch.setattr("src.watcher.settings.inbox_path", tmp_path, raising=False)

    watcher._process_existing_files(handler)

    assert handler._handle_new_file.call_count == 1
    processed_file = handler._handle_new_file.call_args[0][0]
    assert processed_file == audio
    loop.close()


def test_file_deleted_while_waiting_is_not_processed(tmp_path):
    """BUG-06: API-ul a șters fișierul (413 / 409) după ce watcher-ul l-a detectat."""
    loop = asyncio.new_event_loop()
    handler = AudioFileHandler(processor=DummyProcessor(), event_loop=loop)
    audio = tmp_path / "respins.wav"
    audio.write_bytes(b"abc")

    with patch.object(handler, "_wait_for_file_stable", side_effect=lambda p: p.unlink()), patch(
        "src.watcher.asyncio.run_coroutine_threadsafe"
    ) as run_threadsafe:
        handler._handle_new_file(audio)

    assert run_threadsafe.call_count == 0
    assert str(audio) not in handler._processing
    loop.close()


def test_api_part_file_is_ignored(tmp_path):
    """Fișierul în curs de scriere de API (.<nume>.<id>.part) nu e preluat."""
    loop = asyncio.new_event_loop()
    handler = AudioFileHandler(processor=DummyProcessor(), event_loop=loop)
    part = tmp_path / ".sedinta.wav.0123abcd.part"
    part.write_bytes(b"abc")

    with patch("src.watcher.asyncio.run_coroutine_threadsafe") as run_threadsafe:
        handler._handle_new_file(part)

    assert run_threadsafe.call_count == 0
    loop.close()
