# services/audit-retention/src/fix_session_durations.py
# ============================================================
# Corecție unică: durata sesiunilor transcrise (BUG-02)
# ============================================================
# Între 26 octombrie 2026 și remediere, stt-worker aduna a doua oară
# bucățile 1..N la durata deja cumulată de ingest. Durata corectă se
# citește din fișierul lipit (<id>_merged.wav, WAV PCM scris de worker).
#
# Implicit doar listează ce ar corecta:
#   docker compose exec audit-retention python -m src.fix_session_durations
# Aplică corecțiile:
#   docker compose exec audit-retention python -m src.fix_session_durations --apply
# ============================================================

import argparse
import asyncio
import math
import wave
from pathlib import Path
from typing import List, Optional, Tuple

import asyncpg

from src.config import settings

QUERY = """
    SELECT id, title, file_path, duration_seconds
    FROM recordings
    WHERE session_id IS NOT NULL
      AND status = 'completed'
      AND file_path LIKE '%\\_merged.wav'
    ORDER BY created_at
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


async def run(apply: bool) -> None:
    conn = await asyncpg.connect(settings.database_url)
    try:
        fixes, unreadable = corrections(await conn.fetch(QUERY))
        for rec_id, title, stored, actual in fixes:
            print(f"{rec_id}  {stored:>6}s -> {actual:>6}s  {title}")
        for path in unreadable:
            print(f"ATENȚIE: nu pot citi {path} (durata rămâne neschimbată)")
        if not fixes:
            print("Nicio durată de corectat.")
            return
        if not apply:
            print(f"\n{len(fixes)} durate de corectat. Rulează cu --apply ca să le salvezi.")
            return
        async with conn.transaction():
            await conn.executemany(
                "UPDATE recordings SET duration_seconds = $2, updated_at = NOW() WHERE id = $1",
                [(rec_id, actual) for rec_id, _, _, actual in fixes],
            )
        print(f"\n{len(fixes)} durate corectate.")
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Corectează durata sesiunilor transcrise (BUG-02).")
    parser.add_argument("--apply", action="store_true", help="salvează corecțiile (implicit doar le listează)")
    asyncio.run(run(parser.parse_args().apply))


if __name__ == "__main__":
    main()
