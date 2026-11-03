# services/ingest/src/playback.py
# ============================================================
# Copia de redare pentru playerul din browser
# ============================================================
# Playerul din interfață e elementul <audio> al browserului, care decodează
# conținutul MP4 (video H.264, sunet AAC) cu codecurile sistemului. Pe unele
# calculatoare (ex. Windows N fără Media Feature Pack, Firefox pe Linux fără
# codecuri) acestea lipsesc: playerul nu pornește, iar durata apare "NaN",
# deși transcrierea (ffmpeg pe server) merge.
#
# Pentru fiecare MP4 (ex. înregistrările Cisco Meeting Server) facem, o
# singură dată, o copie doar cu sunetul, în MP3 — decodat de toate
# browserele fără codecuri de sistem:
#   <uuid>.mp4  →  <uuid>.play.mp3   (lângă original)
# CBR mono 64 kbps (~29 MB/oră): rata constantă face durata și derularea
# exacte în orice browser; pentru vorbire, calitatea e suficientă.
#
# Originalul rămâne neatins: transcrierea, exportul și backup-ul îl folosesc
# pe el. Copia e servită doar playerului (API), se șterge odată cu
# înregistrarea și nu intră în backup (se poate reface oricând).
#
# Resurse: copiile se fac în fundal, câte una, pe un singur fir, cu prioritate
# minimă (nice/ionice), după ce jobul de transcriere a fost deja trimis.
# ============================================================

import asyncio
import os
import shutil
from pathlib import Path
from typing import List, Optional

from src.logger import get_logger

logger = get_logger(__name__)

PLAYBACK_SUFFIX = ".play.mp3"
PLAYBACK_FORMATS = {"mp4"}
FFMPEG_TIMEOUT_SECONDS = 3 * 3600      # o oră de audio se convertește de obicei în sub un minut


def playback_path(original: Path) -> Path:
    """<dir>/<uuid>.mp4 → <dir>/<uuid>.play.mp3"""
    return original.with_name(original.stem + PLAYBACK_SUFFIX)


def wants_copy(path: Path) -> bool:
    return path.suffix.lower().lstrip(".") in PLAYBACK_FORMATS


def _low_priority(cmd: List[str]) -> List[str]:
    """Cea mai mică prioritate de CPU și disc, ca să nu încetinească transcrierea."""
    prefix: List[str] = []
    if shutil.which("ionice"):
        prefix += ["ionice", "-c", "3"]
    if shutil.which("nice"):
        prefix += ["nice", "-n", "19"]
    return prefix + cmd


def ffmpeg_command(src: Path, dst: Path) -> List[str]:
    return _low_priority([
        "ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-y", "-threads", "1",
        "-i", str(src), "-map", "0:a:0", "-vn", "-sn", "-dn",
        "-ac", "1", "-c:a", "libmp3lame", "-b:a", "64k", "-f", "mp3", str(dst),
    ])


async def create_copy(src: Path) -> Optional[Path]:
    """
    Creează copia de redare dacă lipsește. Întoarce calea copiei sau None.
    ffmpeg rulează ca subproces async: la oprirea serviciului e oprit imediat.
    """
    dst = playback_path(src)
    if not wants_copy(src) or dst.exists() or not src.exists():
        return None
    tmp = dst.with_name(dst.name + ".tmp")
    proc = await asyncio.create_subprocess_exec(
        *ffmpeg_command(src, tmp), stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=FFMPEG_TIMEOUT_SECONDS)
    except (asyncio.CancelledError, asyncio.TimeoutError) as e:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        tmp.unlink(missing_ok=True)
        if isinstance(e, asyncio.CancelledError):
            raise
        logger.warning("playback_copy_timeout", file=src.name)
        return None
    try:
        if proc.returncode != 0:
            raise OSError((stderr or b"").decode("utf-8", "replace")[-500:])
        if not src.exists():                    # înregistrarea a fost ștearsă între timp
            tmp.unlink(missing_ok=True)
            return None
        os.chmod(tmp, 0o644)
        os.replace(tmp, dst)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        logger.warning("playback_copy_failed", file=src.name, error=str(e))
        return None
    logger.info("playback_copy_created", file=src.name, copy=dst.name,
                size_mb=round(dst.stat().st_size / 1024 / 1024, 1))
    return dst


class PlaybackPreparer:
    """Coadă în fundal: o singură copie odată, fără să blocheze procesarea fișierelor noi."""

    def __init__(self) -> None:
        self._queue: "asyncio.Queue[Path]" = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    def schedule(self, path: Path) -> None:
        if wants_copy(path):
            self._queue.put_nowait(path)

    async def backfill(self, database) -> None:
        """Înregistrările MP4 existente (ex. încărcate înainte de această versiune)."""
        try:
            paths = await database.list_playback_candidates(sorted(PLAYBACK_FORMATS))
        except Exception as e:
            logger.warning("playback_backfill_failed", error=str(e))
            return
        pending = [p for p in map(Path, paths) if not playback_path(p).exists()]
        for p in pending:
            self.schedule(p)
        if pending:
            logger.info("playback_backfill_scheduled", files=len(pending))

    async def _run(self) -> None:
        while True:
            path = await self._queue.get()
            try:
                await create_copy(path)
            except Exception as e:                      # nu oprim coada
                logger.warning("playback_copy_error", file=path.name, error=str(e))
            finally:
                self._queue.task_done()
