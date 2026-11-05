# services/audit-retention/src/cleanup_orphans.py
# ============================================================
# Fișiere audio orfane din /data/processed, șterse automat
# ============================================================
# Până la remedierea BUG-01, bucățile sesiunilor din browser rămâneau pe disc
# după transcriere, după ștergerea înregistrării și după expirarea retenției.
# La fiecare trecere a retenției (retention_scheduler.py) se șterg fișierele
# din storage la care nu mai trimite nicio înregistrare
# (recordings.file_path / recording_audio_segments.file_path).
#
# Nu se ating:
#   - fișierele mai noi de ORPHAN_MIN_AGE_HOURS: ingest scrie fișierul înainte
#     de rândul din DB, iar worker-ul mută _merged.wav înainte de salvare;
#   - copia de redare <uuid>.play.mp3 a unei înregistrări existente;
#   - fișierele ascunse și lost+found.
# Protecții: nu se șterge nimic dacă baza nu are înregistrări sau dacă niciun
# fișier al înregistrărilor nu e găsit în storage (alt volum montat, altă bază).
# Fișierele șterse ajung în backup la audio-deleted/ (păstrate BACKUP_RETENTION_DAYS).
# ============================================================

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Set

import asyncpg
import structlog

logger = structlog.get_logger(__name__)

PLAYBACK_SUFFIX = ".play.mp3"   # ingest/playback.py
ORPHAN_MIN_AGE_HOURS = 24

QUERY = """
    SELECT file_path FROM recordings WHERE file_path IS NOT NULL
    UNION
    SELECT file_path FROM recording_audio_segments WHERE file_path IS NOT NULL
"""


@dataclass
class OrphanPurge:
    deleted: int = 0
    deleted_bytes: int = 0
    failed: int = 0
    skipped_reason: Optional[str] = None


def _key(path: Path) -> str:
    return str(path.resolve())


def find_orphans(root: Path, referenced: Iterable[str], min_age_hours: float,
                 now: float = None) -> List[Path]:
    """Fișierele din `root` la care nu trimite nicio înregistrare, mai vechi de min_age_hours."""
    now = time.time() if now is None else now
    keep: Set[str] = set()
    for p in referenced:
        path = Path(p)
        keep.add(_key(path))
        keep.add(_key(path.with_name(path.stem + PLAYBACK_SUFFIX)))
    cutoff = now - min_age_hours * 3600
    orphans = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).parts
        if any(part.startswith(".") or part == "lost+found" for part in rel):
            continue
        if not path.is_file() or _key(path) in keep:
            continue
        if path.stat().st_mtime > cutoff:
            continue
        orphans.append(path)
    return orphans


def purge(root: Path, referenced: List[str], min_age_hours: float, dry_run: bool) -> OrphanPurge:
    """Găsește și (fără dry_run) șterge fișierele orfane. Sincron — rulează într-un thread."""
    if not referenced:
        return OrphanPurge(skipped_reason="nicio înregistrare în baza de date")
    if not any(Path(p).is_file() for p in referenced):
        return OrphanPurge(skipped_reason="niciun fișier al înregistrărilor nu e în storage")
    result = OrphanPurge()
    for path in find_orphans(root, referenced, min_age_hours):
        size = path.stat().st_size
        if not dry_run:
            try:
                path.unlink()
            except OSError as e:
                result.failed += 1
                logger.error("orphan_file_delete_failed", path=str(path), error=str(e))
                continue
        logger.info("orphan_file_deleted", path=str(path), bytes=size, dry_run=dry_run)
        result.deleted += 1
        result.deleted_bytes += size
    return result


async def purge_orphan_files(pool: asyncpg.Pool, root: Path, dry_run: bool = False,
                             min_age_hours: float = ORPHAN_MIN_AGE_HOURS) -> OrphanPurge:
    async with pool.acquire() as conn:
        referenced = [r["file_path"] for r in await conn.fetch(QUERY)]
    result = await asyncio.to_thread(purge, root, referenced, min_age_hours, dry_run)
    if result.skipped_reason:
        logger.warning("orphan_cleanup_skipped", reason=result.skipped_reason)
    return result
