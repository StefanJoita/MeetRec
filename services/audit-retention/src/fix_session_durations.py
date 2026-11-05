# services/audit-retention/src/fix_session_durations.py
# ============================================================
# Durata sesiunilor transcrise (BUG-02), corectată automat
# ============================================================
# Între 26 octombrie 2026 și remediere, stt-worker aduna a doua oară
# bucățile 1..N la durata deja cumulată de ingest. Durata corectă se
# citește din fișierul lipit (<id>_merged.wav, WAV PCM scris de worker).
#
# Rulează la fiecare trecere a retenției (retention_scheduler.py). După prima
# trecere nu mai găsește nimic de corectat; citește doar antetele WAV.
# ============================================================

import asyncio
import math
import wave
from pathlib import Path
from typing import List, Optional, Tuple

import asyncpg
import structlog

logger = structlog.get_logger(__name__)

QUERY = """
    SELECT id, title, file_path, duration_seconds
    FROM recordings
    WHERE session_id IS NOT NULL
      AND status = 'completed'
      AND file_path LIKE '%\\_merged.wav'
"""


def wav_duration_seconds(path: Path) -> Optional[int]:
    """Durata unui WAV PCM, rotunjită în sus la secundă; None dacă nu se poate citi."""
    try:
        with wave.open(str(path), "rb") as w:
            rate = w.getframerate()
            return math.ceil(w.getnframes() / rate) if rate else None
    except (OSError, EOFError, wave.Error):
        return None


def corrections(rows) -> Tuple[List[tuple], List[str]]:
    """(id, titlu, durată în DB, durată reală) pentru duratele greșite + fișierele ilizibile."""
    fixes, unreadable = [], []
    for row in rows:
        actual = wav_duration_seconds(Path(row["file_path"]))
        if actual is None:
            unreadable.append(row["file_path"])
            continue
        stored = row["duration_seconds"] or 0
        if abs(stored - actual) > 1:          # rotunjirile ingest/worker diferă cu ±1 s
            fixes.append((row["id"], row["title"], stored, actual))
    return fixes, unreadable


async def fix_session_durations(pool: asyncpg.Pool, dry_run: bool = False) -> int:
    """Corectează duratele greșite ale sesiunilor. Întoarce câte a corectat (sau ar corecta)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(QUERY)
    fixes, unreadable = await asyncio.to_thread(corrections, rows)
    if unreadable:
        logger.warning("session_duration_unreadable_files", count=len(unreadable),
                       files=unreadable[:20])
    for rec_id, title, stored, actual in fixes:
        logger.info("session_duration_corrected", recording_id=str(rec_id), title=title,
                    old_seconds=stored, new_seconds=actual, dry_run=dry_run)
    if fixes and not dry_run:
        async with pool.acquire() as conn:
            await conn.executemany(
                "UPDATE recordings SET duration_seconds = $2, updated_at = NOW() WHERE id = $1",
                [(rec_id, actual) for rec_id, _, _, actual in fixes],
            )
    return len(fixes)
