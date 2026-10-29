# services/ingest/tests/test_processor_rejected.py
# Fișier respins la validare: apare în listă ca „Eșuat”, cu motivul,
# în loc să dispară în /data/inbox/errors fără nicio urmă în interfață.

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.database import DatabaseClient
from src.processor import FileProcessor
from src.validator import ValidationResult


def make_processor(tmp_path: Path):
    validator = MagicMock()
    validator.validate.return_value = ValidationResult(
        is_valid=False, error_code="INVALID_DURATION",
        error_message="nu am putut determina durata înregistrării.",
    )
    storage = MagicMock()
    storage.move_to_error.side_effect = lambda p: tmp_path / "errors" / p.name
    database = MagicMock()
    database.get_app_setting = AsyncMock(return_value=None)
    database.create_rejected_recording = AsyncMock()
    return FileProcessor(validator=validator, storage=storage, database=database, publisher=MagicMock())


def inbox_file(tmp_path: Path, meta: dict) -> Path:
    f = tmp_path / "Voce 261006_113235.m4a"
    f.write_bytes(b"x" * 1234)
    f.with_suffix(".m4a.meetrec-meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return f


@pytest.mark.asyncio
async def test_rejected_upload_becomes_failed_recording_with_reason(tmp_path):
    proc = make_processor(tmp_path)
    f = inbox_file(tmp_path, {"uploaded_via": "api", "title": "Conferință", "meeting_date": "2026-10-06"})

    assert await proc.process(f) is False

    proc.database.create_rejected_recording.assert_awaited_once()
    kwargs = proc.database.create_rejected_recording.await_args.kwargs
    assert kwargs["filename"] == "Voce 261006_113235.m4a"
    assert kwargs["file_path"] == tmp_path / "errors" / "Voce 261006_113235.m4a"
    assert kwargs["file_size_bytes"] == 1234
    assert kwargs["error_message"] == "Fișierul a fost respins: nu am putut determina durata înregistrării."
    assert kwargs["user_meta"]["title"] == "Conferință"


@pytest.mark.asyncio
async def test_rejected_session_segment_does_not_create_recording(tmp_path):
    proc = make_processor(tmp_path)
    f = inbox_file(tmp_path, {"uploaded_via": "api", "session_id": "8dc38f9c-c5ab-4298-8521-fe0fbb699fe3",
                              "segment_index": 3})

    assert await proc.process(f) is False

    proc.storage.move_to_error.assert_called_once()
    proc.database.create_rejected_recording.assert_not_awaited()


@pytest.mark.asyncio
async def test_db_error_while_recording_rejection_does_not_crash(tmp_path):
    proc = make_processor(tmp_path)
    proc.database.create_rejected_recording.side_effect = ConnectionError("db down")
    f = inbox_file(tmp_path, {"uploaded_via": "api"})

    assert await proc.process(f) is False


# ── SQL-ul înregistrării respinse ────────────────────────────

def make_client():
    conn = AsyncMock()
    acq = AsyncMock()
    acq.__aenter__ = AsyncMock(return_value=conn)
    acq.__aexit__ = AsyncMock(return_value=False)
    client = DatabaseClient()
    client._pool = MagicMock(acquire=MagicMock(return_value=acq))
    return client, conn


@pytest.mark.asyncio
@pytest.mark.parametrize("filename, expected_format", [
    ("sedinta.m4a", "m4a"),
    ("sedinta.MP3", "mp3"),
    ("Prima parte conferinta.m4a.mp4", "mp4"),
    ("sedinta.avi", "unknown"),   # extensie respinsă: nu e în tipul audio_format
])
async def test_rejected_recording_row(filename, expected_format):
    client, conn = make_client()

    await client.create_rejected_recording(
        filename=filename, file_path=Path("/data/inbox/errors") / filename, file_size_bytes=10,
        error_message="Fișierul a fost respins: x", user_meta={"meeting_date": "2026-10-06"},
    )

    sql, *args = conn.execute.await_args.args
    assert "'failed'" in sql
    assert "INSERT INTO transcripts" not in sql          # nimic de reîncercat
    assert args[10] == expected_format
    assert args[11] == "Fișierul a fost respins: x"
    assert str(args[2]) == "2026-10-06"


@pytest.mark.asyncio
async def test_rejected_recording_does_not_block_reupload_of_same_file():
    """Hash-ul stocat nu e al fișierului: după corectare, același fișier nu e luat drept duplicat."""
    client, conn = make_client()

    await client.create_rejected_recording(filename="a.m4a", file_path=Path("/x/a.m4a"), file_size_bytes=1,
                                           error_message="x")
    await client.create_rejected_recording(filename="a.m4a", file_path=Path("/x/a.m4a"), file_size_bytes=1,
                                           error_message="x")

    hashes = [c.args[10] for c in conn.execute.await_args_list]
    assert len(set(hashes)) == 2 and all(len(h) == 64 for h in hashes)
