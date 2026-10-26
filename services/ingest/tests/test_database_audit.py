# services/ingest/tests/test_database_audit.py
# Fișierele copiate direct în inbox (fără API) lasă o urmă în jurnalul de audit;
# încărcările prin API și segmentele de sesiune sunt jurnalizate de API.

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.database import DatabaseClient
from src.validator import AudioMetadata


def make_client():
    conn = AsyncMock()
    tx = AsyncMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx)
    acq = AsyncMock()
    acq.__aenter__ = AsyncMock(return_value=conn)
    acq.__aexit__ = AsyncMock(return_value=False)
    client = DatabaseClient()
    client._pool = MagicMock(acquire=MagicMock(return_value=acq))
    return client, conn


METADATA = AudioMetadata(filename="sedinta_ca.mp3", file_path=Path("/data/inbox/sedinta_ca.mp3"),
                         file_size_bytes=2_000_000, file_hash_sha256="ab" * 32, audio_format="mp3",
                         duration_seconds=600)


def audit_inserts(conn):
    return [c.args for c in conn.execute.call_args_list if "INSERT INTO audit_logs" in c.args[0]]


@pytest.mark.asyncio
async def test_direct_inbox_file_is_audited():
    client, conn = make_client()

    recording_id = await client.create_recording(METADATA, Path("/data/processed/x.mp3"),
                                                 user_meta={"title": "Ședința CA"})

    [(sql, _id, rid, details)] = audit_inserts(conn)
    assert "'UPLOAD'" in sql and rid == recording_id
    assert json.loads(details) == {"resource_name": "Ședința CA", "filename": "sedinta_ca.mp3",
                                   "size_bytes": 2_000_000, "sha256": "ab" * 32, "source": "inbox_folder"}


@pytest.mark.asyncio
@pytest.mark.parametrize("user_meta", [
    {"uploaded_via": "api", "title": "X"},                 # jurnalizat de API
    {"session_id": str(uuid.uuid4())},                     # sesiune: jurnalizată de API
])
async def test_api_uploads_and_sessions_are_not_audited_twice(user_meta):
    client, conn = make_client()

    await client.create_recording(METADATA, Path("/data/processed/x.mp3"), user_meta=user_meta)

    assert audit_inserts(conn) == []


# ── Durata sesiunilor multi-segment ──────────────────────────
# Înregistrarea din browser trimite un segment la 5 minute: durata afișată
# în timpul transcrierii trebuie să cuprindă toate segmentele primite.

@pytest.mark.asyncio
async def test_attached_segment_adds_its_duration_to_recording():
    client, conn = make_client()
    recording_id = str(uuid.uuid4())
    segment = AudioMetadata(filename="inregistrare_001.wav", file_path=Path("/data/inbox/inregistrare_001.wav"),
                            file_size_bytes=3_000_000, file_hash_sha256="cd" * 32, audio_format="wav",
                            duration_seconds=95)

    await client.create_audio_segment(recording_id, 1, Path("/data/processed/y.wav"), segment)

    [update] = [c.args for c in conn.execute.call_args_list if c.args[0].lstrip().startswith("UPDATE recordings")]
    assert "duration_seconds = COALESCE(duration_seconds, 0) + $2" in update[0]
    assert update[1:] == (recording_id, 95)
    conn.transaction.assert_called_once()   # segmentul și durata, împreună sau deloc


@pytest.mark.asyncio
async def test_primary_file_duration_includes_segments_already_attached():
    client, conn = make_client()

    await client.update_primary_file(str(uuid.uuid4()), METADATA, Path("/data/processed/x.mp3"))

    [(sql, *_)] = [c.args for c in conn.execute.call_args_list]
    assert "SUM(duration_seconds) FROM recording_audio_segments" in sql
