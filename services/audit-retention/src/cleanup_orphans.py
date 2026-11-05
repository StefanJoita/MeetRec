# services/audit-retention/src/cleanup_orphans.py
# ============================================================
# Curățare unică: fișiere audio orfane din /data/processed
# ============================================================
# Până la remedierea BUG-01, bucățile sesiunilor din browser rămâneau pe disc
# după transcriere, după ștergerea înregistrării și după expirarea retenției.
# Scriptul găsește fișierele din storage la care nu mai trimite nicio
# înregistrare (recordings.file_path / recording_audio_segments.file_path).
#
# Implicit doar listează ce ar șterge:
#   docker compose exec audit-retention python -m src.cleanup_orphans
# Șterge:
#   docker compose exec audit-retention python -m src.cleanup_orphans --apply
#
# Nu se ating:
#   - fișierele mai noi de --min-age-hours (implicit 24): ingest scrie fișierul
#     înainte de rândul din DB, iar worker-ul mută _merged.wav înainte de salvare;
#   - copia de redare <uuid>.play.mp3 a unei înregistrări existente;
#   - fișierele ascunse și lost+found.
# Fișierele șterse ajung în backup la audio-deleted/ (păstrate BACKUP_RETENTION_DAYS).
# ============================================================

import argparse
import asyncio
import time
from pathlib import Path
from typing import Iterable, List, Set

import asyncpg

from src.config import settings

PLAYBACK_SUFFIX = ".play.mp3"   # ingest/playback.py

QUERY = """
    SELECT file_path FROM recordings WHERE file_path IS NOT NULL
    UNION
    SELECT file_path FROM recording_audio_segments WHERE file_path IS NOT NULL
"""


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


def _size(paths: List[Path]) -> str:
    total = sum(p.stat().st_size for p in paths)
    return f"{total / 1024**3:.2f} GB" if total >= 1024**3 else f"{total / 1024**2:.1f} MB"


async def run(apply: bool, min_age_hours: float) -> int:
    conn = await asyncpg.connect(settings.database_url)
    try:
        referenced = [r["file_path"] for r in await conn.fetch(QUERY)]
    finally:
        await conn.close()

    root = settings.audio_storage_path
    orphans = find_orphans(root, referenced, min_age_hours)
    for path in orphans:
        print(path)
    if not orphans:
        print("Niciun fișier orfan.")
        return 0
    # Protecție: baza goală (sau alta decât cea a storage-ului) ar marca totul drept orfan
    if not referenced:
        print(f"\nOPRIT: nicio înregistrare în baza de date, dar {len(orphans)} fișiere în {root}. "
              "Verifică DATABASE_URL; nu șterg nimic.")
        return 1
    print(f"\n{len(orphans)} fișiere orfane, {_size(orphans)}.")
    if not apply:
        print("Rulează cu --apply ca să le ștergi.")
        return 0

    failed = 0
    for path in orphans:
        try:
            path.unlink()
        except OSError as e:
            failed += 1
            print(f"EROARE: {path}: {e}")
    print(f"Șterse: {len(orphans) - failed}" + (f", eșuate: {failed}" if failed else "") + ".")
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Șterge fișierele audio orfane din storage (BUG-01).")
    parser.add_argument("--apply", action="store_true", help="șterge fișierele (implicit doar le listează)")
    parser.add_argument("--min-age-hours", type=float, default=24,
                        help="ignoră fișierele mai noi de atât (implicit 24)")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.apply, args.min_age_hours)))


if __name__ == "__main__":
    main()
