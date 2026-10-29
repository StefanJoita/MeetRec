# services/audit-retention/src/backup.py
# ============================================================
# Backup zilnic: baza de date, fișierele audio și configurația
# ============================================================
# Structura în BACKUP_PATH (/backups, montat din BACKUP_HOST_PATH de pe server):
#   db/meetrec-AAAALLZZ-HHMMSS.dump        pg_dump -Fc (rotație: zilnice + săptămânale)
#   config/config-AAAALLZZ-HHMMSS.tar.gz   .env + nginx/ssl (aceeași rotație)
#   audio/AAAA/LL/ZZ/<uuid>.<ext>          oglinda volumului audio; se copiază doar
#                                          fișierele noi (cele existente nu se modifică)
#   audio-deleted/AAAALLZZ/...             fișierele șterse din aplicație, păstrate
#                                          BACKUP_DELETED_AUDIO_DAYS zile
#   last-backup.json                       starea ultimei rulări (și în Redis, pentru API)
#
# Pornire: zilnic la BACKUP_HOUR (prima verificare după ora respectivă) sau la cerere,
# din Administrare → Stare sistem (API-ul pune cererea în Redis).
# Restaurare: restore-backup.sh din pachetul offline (docs/INSTALL-OFFLINE.md §9.3).
# ============================================================

import asyncio
import json
import os
import re
import shutil
import tarfile
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

import asyncpg
import redis.asyncio as aioredis
import structlog

from src import runtime_settings
from src.config import settings
from src.database import DatabaseClient

logger = structlog.get_logger(__name__)

# Chei Redis comune cu API-ul (services/api/src/routers/admin.py)
STATUS_KEY = "meetrec:backup:status"
REQUEST_KEY = "meetrec:backup:request"

_STAMP = "%Y%m%d-%H%M%S"
_STAMPED = re.compile(r"-(\d{8}-\d{6})\.")
_PARTIAL = ".partial"


# ── Rotație ──────────────────────────────────────────────────

def select_to_keep(stamps: Iterable[datetime], keep_daily: int, keep_weekly: int) -> Set[datetime]:
    """
    Cel mai nou backup din fiecare dintre ultimele `keep_daily` zile cu backup
    și din fiecare dintre ultimele `keep_weekly` săptămâni (ISO) cu backup.
    """
    keep: Set[datetime] = set()
    days: Dict[date, datetime] = {}
    weeks: Dict[Tuple[int, int], datetime] = {}
    for ts in sorted(stamps, reverse=True):
        days.setdefault(ts.date(), ts)
        weeks.setdefault(tuple(ts.isocalendar())[:2], ts)
    keep.update(list(days.values())[:keep_daily])
    keep.update(list(weeks.values())[:keep_weekly])
    return keep


def rotate(directory: Path, keep_daily: int, keep_weekly: int) -> List[Path]:
    """Șterge backup-urile din `directory` care nu mai sunt păstrate. Întoarce ce a șters."""
    stamped: Dict[datetime, Path] = {}
    for f in directory.glob("*"):
        m = _STAMPED.search(f.name)
        if f.is_file() and m and not f.name.endswith(_PARTIAL):
            stamped[datetime.strptime(m.group(1), _STAMP)] = f
    keep = select_to_keep(stamped, keep_daily, keep_weekly)
    removed = []
    for ts, f in stamped.items():
        if ts not in keep:
            f.unlink()
            removed.append(f)
    return removed


# ── Audio ────────────────────────────────────────────────────

def _files(root: Path) -> Dict[Path, int]:
    """{cale relativă: dimensiune} pentru fișierele din `root` (fără cele în curs de copiere)."""
    if not root.exists():
        return {}
    return {
        p.relative_to(root): p.stat().st_size
        for p in root.rglob("*")
        if p.is_file() and not p.name.endswith(_PARTIAL)
    }


def sync_audio(source: Path, mirror: Path, deleted_root: Path, today: date) -> Dict[str, int]:
    """
    Copiază în `mirror` fișierele noi sau incomplete din `source`. Fișierele din
    `mirror` care nu mai există în `source` (șterse din aplicație) sunt mutate în
    deleted_root/AAAALLZZ/, nu șterse.
    """
    src, dst = _files(source), _files(mirror)
    copied = copied_bytes = moved = 0
    for rel, size in src.items():
        if dst.get(rel) == size:
            continue
        target = mirror / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + _PARTIAL)
        shutil.copy2(source / rel, tmp)
        os.replace(tmp, target)
        copied += 1
        copied_bytes += size
    for rel in dst.keys() - src.keys():
        target = deleted_root / today.strftime("%Y%m%d") / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(mirror / rel), str(target))
        moved += 1
    return {"audio_files": len(src), "audio_bytes": sum(src.values()),
            "audio_copied": copied, "audio_copied_bytes": copied_bytes, "audio_moved_to_deleted": moved}


def purge_deleted(deleted_root: Path, days: int, today: date) -> int:
    """Șterge din audio-deleted/ zilele mai vechi de `days`. Întoarce câte zile a șters."""
    if not deleted_root.exists():
        return 0
    removed = 0
    for d in deleted_root.iterdir():
        try:
            day = datetime.strptime(d.name, "%Y%m%d").date()
        except ValueError:
            continue
        if d.is_dir() and (today - day).days > days:
            shutil.rmtree(d)
            removed += 1
    return removed


def is_backed_up(file_path: Optional[str]) -> bool:
    """Fișierul audio al unei înregistrări există, complet, în oglinda din backup."""
    if not file_path:
        return True                      # nimic de pierdut (ex. sesiune fără audio)
    source = Path(file_path)
    try:
        rel = source.relative_to(settings.audio_storage_path)
    except ValueError:
        return False
    if not source.exists():
        return True                      # fișierul a dispărut deja; nu ține retenția în loc
    copy = settings.backup_path / "audio" / rel
    return copy.exists() and copy.stat().st_size == source.stat().st_size


# ── Baza de date și configurația ─────────────────────────────

async def dump_database(dest: Path) -> int:
    """pg_dump -Fc în `dest`. Întoarce dimensiunea; ridică RuntimeError la eșec."""
    tmp = dest.with_name(dest.name + _PARTIAL)
    proc = await asyncio.create_subprocess_exec(
        "pg_dump", "--format=custom", f"--file={tmp}", f"--dbname={settings.database_url}",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"pg_dump: {err.decode(errors='replace').strip()[-500:]}")
    os.replace(tmp, dest)
    return dest.stat().st_size


def archive_config(config_dir: Path, dest: Path) -> int:
    """`.env` și `ssl/` (montate read-only) într-o arhivă tar.gz. 0 dacă nu există nimic."""
    items = [p for p in (config_dir / ".env", config_dir / "ssl") if p.exists()]
    if not items:
        return 0
    tmp = dest.with_name(dest.name + _PARTIAL)
    with tarfile.open(tmp, "w:gz") as tar:
        for p in items:
            tar.add(p, arcname=p.name)
    os.replace(tmp, dest)
    return dest.stat().st_size


# ── O rulare completă ────────────────────────────────────────

def _check_destination(root: Path) -> None:
    if not root.is_dir():
        raise RuntimeError(f"Destinația backup-ului nu există: {root} (BACKUP_HOST_PATH).")
    probe = root / f".write-test-{uuid.uuid4().hex}"
    try:
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as e:
        raise RuntimeError(f"Nu se poate scrie în destinația backup-ului: {e}") from e


async def run_backup(trigger: str, now: Optional[datetime] = None) -> Dict:
    """Rulează backup-ul. Nu ridică excepții: întoarce starea (state = ok | failed)."""
    now = now or datetime.now()
    root = settings.backup_path
    status: Dict = {"state": "failed", "trigger": trigger, "started_at": now.isoformat(timespec="seconds")}
    try:
        _check_destination(root)
        for sub in ("db", "config", "audio", "audio-deleted"):
            (root / sub).mkdir(exist_ok=True)
        stamp = now.strftime(_STAMP)

        db_file = root / "db" / f"meetrec-{stamp}.dump"
        status["db_file"] = db_file.name
        status["db_bytes"] = await dump_database(db_file)
        status["config_bytes"] = await asyncio.to_thread(
            archive_config, settings.backup_config_path, root / "config" / f"config-{stamp}.tar.gz")
        status.update(await asyncio.to_thread(
            sync_audio, settings.audio_storage_path, root / "audio", root / "audio-deleted", now.date()))

        await asyncio.to_thread(rotate, root / "db", settings.backup_keep_daily, settings.backup_keep_weekly)
        await asyncio.to_thread(rotate, root / "config", settings.backup_keep_daily, settings.backup_keep_weekly)
        await asyncio.to_thread(purge_deleted, root / "audio-deleted", settings.backup_deleted_audio_days, now.date())
        status["state"] = "ok"
    except Exception as e:
        status["error"] = str(e)
        logger.error("backup_failed", error=str(e), trigger=trigger)
    status["finished_at"] = datetime.now().isoformat(timespec="seconds")
    try:
        status["free_bytes"] = shutil.disk_usage(root).free
    except OSError:
        pass
    if status["state"] == "ok":
        logger.info("backup_completed", **{k: v for k, v in status.items() if k != "state"})
    return status


def read_last_status() -> Optional[Dict]:
    try:
        return json.loads((settings.backup_path / "last-backup.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_last_status(status: Dict) -> None:
    try:
        (settings.backup_path / "last-backup.json").write_text(json.dumps(status), encoding="utf-8")
    except OSError as e:
        logger.warning("backup_status_write_failed", error=str(e))


def is_due(last: Optional[Dict], now: datetime) -> bool:
    """
    Backup-ul programat: o dată pe zi, la prima verificare după BACKUP_HOUR. Dacă serviciul
    a fost oprit la ora respectivă, rulează la pornire. Un eșec se reia a doua zi
    (sau manual); rulările manuale nu țin locul celei programate.
    """
    if not settings.backup_enabled or now.hour < settings.backup_hour:
        return False
    return (last or {}).get("last_scheduled_day") != now.date().isoformat()


async def log_backup(pool: asyncpg.Pool, status: Dict) -> None:
    """Urmă în jurnalul de audit pentru fiecare rulare (reușită sau eșuată)."""
    details = {k: status.get(k) for k in ("trigger", "db_bytes", "audio_files", "audio_copied",
                                          "audio_moved_to_deleted", "error") if status.get(k) is not None}
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO audit_logs (id, action, resource_type, details, success, user_ip)
            VALUES ($1, 'CREATE', 'backup', $2, $3, '127.0.0.1')
            """,
            str(uuid.uuid4()), json.dumps(details, ensure_ascii=False), status["state"] == "ok",
        )


class BackupScheduler:
    """Verifică la fiecare BACKUP_CHECK_INTERVAL_SECONDS dacă e momentul backup-ului."""

    def __init__(self, db: DatabaseClient):
        self._db = db
        self._running = False
        self._stop_event = asyncio.Event()
        self._redis: Optional[aioredis.Redis] = None
        self._last: Optional[Dict] = None

    async def start(self) -> None:
        self._running = True
        self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        self._last = read_last_status()
        if self._last:
            await self._publish(self._last)
        logger.info("backup_scheduler_started", enabled=settings.backup_enabled,
                    hour=settings.backup_hour, path=str(settings.backup_path))
        try:
            while self._running:
                try:
                    await self._tick()
                except Exception as e:
                    logger.error("backup_scheduler_error", error=str(e))
                try:
                    await asyncio.wait_for(self._stop_event.wait(),
                                           timeout=settings.backup_check_interval_seconds)
                except asyncio.TimeoutError:
                    pass
        finally:
            await self._redis.aclose()
            logger.info("backup_scheduler_stopped")

    def stop(self) -> None:
        self._running = False
        self._stop_event.set()

    async def _tick(self) -> None:
        await runtime_settings.refresh(self._db.pool)      # Administrare → Setări
        now = datetime.now()
        requested = await self._redis.getdel(REQUEST_KEY)
        if requested:
            await self._run("manual", now)
        elif is_due(self._last, now):
            await self._run("scheduled", now)

    async def _run(self, trigger: str, now: datetime) -> None:
        await self._publish({**(self._last or {}), "state": "running", "trigger": trigger,
                             "started_at": now.isoformat(timespec="seconds")})
        status = await run_backup(trigger, now)
        status["last_scheduled_day"] = (now.date().isoformat() if trigger == "scheduled"
                                        else (self._last or {}).get("last_scheduled_day"))
        if status["state"] == "ok":
            status["last_success_at"] = status["finished_at"]
        elif self._last and self._last.get("last_success_at"):
            status["last_success_at"] = self._last["last_success_at"]
        self._last = status
        write_last_status(status)
        await self._publish(status)
        try:
            await log_backup(self._db.pool, status)
        except Exception as e:
            logger.warning("backup_audit_failed", error=str(e))

    async def _publish(self, status: Dict) -> None:
        try:
            await self._redis.set(STATUS_KEY, json.dumps(status))
        except Exception as e:
            logger.warning("backup_status_publish_failed", error=str(e))
