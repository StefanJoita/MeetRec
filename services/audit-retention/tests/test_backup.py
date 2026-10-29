# services/audit-retention/tests/test_backup.py
# ============================================================
# Backup zilnic: rotație, oglinda audio, programare, legătura cu retenția
# ============================================================

import json
import tarfile
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest

from src import backup, runtime_settings
from src.backup import (
    BackupScheduler, is_backed_up, is_due, purge_deleted, rotate, select_to_keep, sync_audio,
)
from src.config import settings
from src.retention_policy import RecordingToDelete
from src.retention_scheduler import RetentionScheduler


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    for k in runtime_settings.KEYS:
        monkeypatch.setattr(settings, k, getattr(settings, k))
    audio, dest, cfg = tmp_path / "processed", tmp_path / "backups", tmp_path / "config"
    for d in (audio, dest, cfg):
        d.mkdir()
    monkeypatch.setattr(settings, "audio_storage_path", audio)
    monkeypatch.setattr(settings, "backup_path", dest)
    monkeypatch.setattr(settings, "backup_config_path", cfg)
    monkeypatch.setattr(runtime_settings, "refresh", AsyncMock(return_value={}))
    return audio, dest, cfg


def write(path: Path, data: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


class TestRotation:

    def test_keeps_newest_per_day_and_per_week(self):
        start = datetime(2026, 10, 1, 2, 0)
        stamps = [start + timedelta(days=i) for i in range(28)]
        stamps.append(start + timedelta(days=27, hours=10))          # două backup-uri în aceeași zi

        keep = select_to_keep(stamps, keep_daily=7, keep_weekly=4)

        days = sorted({ts.date() for ts in keep})
        assert start + timedelta(days=27, hours=10) in keep            # cel mai nou din ziua lui
        assert start + timedelta(days=27) not in keep
        assert days[-7:] == [date(2026, 10, 22) + timedelta(days=i) for i in range(7)]
        assert len({tuple(ts.isocalendar())[:2] for ts in keep}) == 4

    def test_rotate_deletes_only_unkept_stamped_files(self, tmp_path):
        d = tmp_path / "db"
        for i in range(10):
            write(d / f"meetrec-202610{10 + i:02d}-020000.dump")
        write(d / "notita.txt")
        write(d / "meetrec-20261001-020000.dump.partial")

        removed = rotate(d, keep_daily=3, keep_weekly=0)

        names = sorted(p.name for p in d.iterdir())
        assert len(removed) == 7
        assert "meetrec-20261019-020000.dump" in names and "meetrec-20261016-020000.dump" not in names
        assert "notita.txt" in names and "meetrec-20261001-020000.dump.partial" in names


class TestAudioMirror:

    def test_copies_new_files_and_keeps_existing(self, isolated):
        audio, dest, _ = isolated
        write(audio / "2026/10/29/a.m4a", b"aaaa")
        write(audio / "2026/10/29/b.mp3", b"bb")
        write(dest / "audio/2026/10/29/a.m4a", b"aaaa")

        result = sync_audio(audio, dest / "audio", dest / "audio-deleted", date(2026, 10, 29))

        assert (dest / "audio/2026/10/29/b.mp3").read_bytes() == b"bb"
        assert result["audio_copied"] == 1 and result["audio_copied_bytes"] == 2
        assert result["audio_files"] == 2

    def test_incomplete_copy_is_redone(self, isolated):
        audio, dest, _ = isolated
        write(audio / "a.wav", b"complet")
        write(dest / "audio/a.wav", b"jum")

        sync_audio(audio, dest / "audio", dest / "audio-deleted", date(2026, 10, 29))

        assert (dest / "audio/a.wav").read_bytes() == b"complet"

    def test_deleted_from_app_moves_to_deleted_folder(self, isolated):
        audio, dest, _ = isolated
        write(dest / "audio/2026/01/02/sters.m4a", b"vechi")

        result = sync_audio(audio, dest / "audio", dest / "audio-deleted", date(2026, 10, 29))

        assert not (dest / "audio/2026/01/02/sters.m4a").exists()
        assert (dest / "audio-deleted/20261029/2026/01/02/sters.m4a").read_bytes() == b"vechi"
        assert result["audio_moved_to_deleted"] == 1

    def test_purge_deleted_after_n_days(self, tmp_path):
        root = tmp_path / "audio-deleted"
        write(root / "20260901/x.m4a")
        write(root / "20261020/y.m4a")
        (root / "altceva").mkdir()

        removed = purge_deleted(root, days=30, today=date(2026, 10, 29))

        assert removed == 1
        assert sorted(p.name for p in root.iterdir()) == ["20261020", "altceva"]


class TestRetentionGate:

    def test_backed_up_only_when_copy_is_complete(self, isolated):
        audio, dest, _ = isolated
        f = write(audio / "2026/10/29/a.m4a", b"1234")
        assert not is_backed_up(str(f))
        write(dest / "audio/2026/10/29/a.m4a", b"12")
        assert not is_backed_up(str(f))
        write(dest / "audio/2026/10/29/a.m4a", b"1234")
        assert is_backed_up(str(f))

    def test_missing_source_or_no_file_does_not_block_retention(self, isolated):
        audio, _, _ = isolated
        assert is_backed_up(None)
        assert is_backed_up(str(audio / "disparut.m4a"))

    @pytest.mark.asyncio
    async def test_retention_waits_for_backup(self, isolated, monkeypatch):
        audio, dest, _ = isolated
        f = write(audio / "2026/01/01/vechi.m4a", b"1234")
        rec = RecordingToDelete(id="r1", title="Veche", file_path=str(f), retain_until=date(2026, 1, 1))
        import src.retention_scheduler as rs
        monkeypatch.setattr(rs, "fetch_expired_recordings", AsyncMock(return_value=[rec]))
        delete = AsyncMock(return_value=True)
        monkeypatch.setattr(rs, "delete_recording", delete)
        monkeypatch.setattr(rs, "log_retention_delete", AsyncMock())
        monkeypatch.setattr(rs, "delete_expired_audit_logs", AsyncMock(return_value=0))
        monkeypatch.setattr(rs, "log_audit_purge", AsyncMock())
        monkeypatch.setattr(rs.runtime_settings, "refresh", AsyncMock(return_value={}))
        scheduler = RetentionScheduler(MagicMock())

        settings.backup_enabled = True
        await scheduler._run_once()
        delete.assert_not_called()                     # nu e încă în backup

        write(dest / "audio/2026/01/01/vechi.m4a", b"1234")
        await scheduler._run_once()
        delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_retention_unchanged_when_backup_disabled(self, isolated, monkeypatch):
        audio, _, _ = isolated
        f = write(audio / "vechi.m4a")
        rec = RecordingToDelete(id="r1", title="Veche", file_path=str(f), retain_until=date(2026, 1, 1))
        import src.retention_scheduler as rs
        monkeypatch.setattr(rs, "fetch_expired_recordings", AsyncMock(return_value=[rec]))
        delete = AsyncMock(return_value=True)
        monkeypatch.setattr(rs, "delete_recording", delete)
        monkeypatch.setattr(rs, "log_retention_delete", AsyncMock())
        monkeypatch.setattr(rs, "delete_expired_audit_logs", AsyncMock(return_value=0))
        monkeypatch.setattr(rs, "log_audit_purge", AsyncMock())
        monkeypatch.setattr(rs.runtime_settings, "refresh", AsyncMock(return_value={}))

        settings.backup_enabled = False
        await RetentionScheduler(MagicMock())._run_once()

        delete.assert_called_once()


class TestSchedule:

    def test_runs_once_a_day_after_the_hour(self):
        settings.backup_enabled, settings.backup_hour = True, 2
        assert not is_due(None, datetime(2026, 10, 29, 1, 59))
        assert is_due(None, datetime(2026, 10, 29, 2, 0))
        assert is_due(None, datetime(2026, 10, 29, 15, 0))         # serverul era oprit la 02:00
        done = {"last_scheduled_day": "2026-10-29", "state": "failed"}
        assert not is_due(done, datetime(2026, 10, 29, 23, 0))      # eșecul se reia mâine sau manual
        assert is_due(done, datetime(2026, 10, 30, 2, 1))

    def test_manual_run_does_not_replace_scheduled(self):
        settings.backup_enabled, settings.backup_hour = True, 2
        manual = {"trigger": "manual", "state": "ok", "last_scheduled_day": "2026-10-28"}
        assert is_due(manual, datetime(2026, 10, 29, 3, 0))

    def test_disabled(self):
        settings.backup_enabled = False
        assert not is_due(None, datetime(2026, 10, 29, 12, 0))


class TestRun:

    @pytest.mark.asyncio
    async def test_full_run_writes_db_config_audio(self, isolated, monkeypatch):
        audio, dest, cfg = isolated
        write(audio / "2026/10/29/a.m4a", b"audio")
        write(cfg / ".env", b"SECRET=1")
        write(cfg / "ssl/fullchain.pem", b"cert")

        async def fake_dump(target: Path) -> int:
            target.write_bytes(b"dump")
            return 4
        monkeypatch.setattr(backup, "dump_database", fake_dump)

        status = await backup.run_backup("manual", datetime(2026, 10, 29, 2, 0, 5))

        assert status["state"] == "ok", status.get("error")
        assert (dest / "db/meetrec-20261029-020005.dump").exists()
        assert (dest / "audio/2026/10/29/a.m4a").read_bytes() == b"audio"
        with tarfile.open(dest / "config/config-20261029-020005.tar.gz") as tar:
            assert sorted(tar.getnames()) == [".env", "ssl", "ssl/fullchain.pem"]

    @pytest.mark.asyncio
    async def test_missing_destination_fails_without_raising(self, isolated, monkeypatch, tmp_path):
        monkeypatch.setattr(settings, "backup_path", tmp_path / "nu-exista")

        status = await backup.run_backup("scheduled")

        assert status["state"] == "failed"
        assert "nu există" in status["error"]

    @pytest.mark.asyncio
    async def test_pg_dump_failure_is_reported(self, isolated, monkeypatch):
        monkeypatch.setattr(backup, "dump_database", AsyncMock(side_effect=RuntimeError("pg_dump: conexiune refuzată")))

        status = await backup.run_backup("scheduled")

        assert status["state"] == "failed"
        assert "conexiune refuzată" in status["error"]


class TestScheduler:

    @pytest.mark.asyncio
    async def test_manual_request_from_api_runs_and_publishes_status(self, isolated, monkeypatch):
        _, dest, _ = isolated
        redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        await redis.set(backup.REQUEST_KEY, json.dumps({"by": "admin"}))
        monkeypatch.setattr(backup, "run_backup", AsyncMock(return_value={
            "state": "ok", "trigger": "manual", "started_at": "x", "finished_at": "2026-10-29T10:00:00"}))
        log = AsyncMock()
        monkeypatch.setattr(backup, "log_backup", log)
        settings.backup_enabled, settings.backup_hour = True, 23

        scheduler = BackupScheduler(MagicMock())
        scheduler._redis = redis
        await scheduler._tick()

        published = json.loads(await redis.get(backup.STATUS_KEY))
        assert published["state"] == "ok" and published["last_success_at"] == "2026-10-29T10:00:00"
        assert not await redis.exists(backup.REQUEST_KEY)
        assert json.loads((dest / "last-backup.json").read_text())["trigger"] == "manual"
        log.assert_awaited_once()
