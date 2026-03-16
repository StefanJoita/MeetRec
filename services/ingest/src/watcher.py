# services/ingest/src/watcher.py
# ============================================================
# File Watcher — Monitorizează inbox-ul pentru fișiere noi
# ============================================================
#
# Cum funcționează watchdog?
# Sistemul de operare (Linux) are un API numit "inotify"
# care notifică aplicațiile când se modifică fișiere.
# watchdog e o librărie Python care abstractizează inotify.
#
# De ce inotify și nu "verifică la fiecare secundă"?
# Polling (verifică la fiecare secundă):
#   - Consumă CPU chiar dacă nu e nimic nou
#   - Delay de până la 1 secundă
#
# inotify (event-based):
#   - Zero CPU când nu sunt fișiere noi
#   - Notificare instantanee
# ============================================================

import asyncio
import time
from pathlib import Path
from typing import Optional

from watchdog.observers import Observer
from watchdog.events import (
    FileSystemEventHandler,
    FileCreatedEvent,
    FileMovedEvent,
)

from src.config import settings
from src.logger import get_logger
from src.processor import FileProcessor 

logger = get_logger(__name__)


class AudioFileHandler(FileSystemEventHandler):
    """
    Handler pentru evenimente de sistem de fișiere.
    Watchdog apelează metodele acestei clase când detectează modificări.
    
    Moștenire (Inheritance) 101:
    FileSystemEventHandler e clasa "părinte" cu metode goale.
    Noi "suprascriem" (override) metodele care ne interesează.
    """

    def __init__(self, processor: FileProcessor, event_loop: asyncio.AbstractEventLoop):
        super().__init__()  # inițializăm clasa părinte
        self.processor = processor
        self._event_loop = event_loop
        # Set de fișiere în procesare (evităm duplicatele)
        self._processing: set = set()

    def on_created(self, event: FileCreatedEvent) -> None:
        """
        Apelat când un fișier NOU apare în inbox.
        Cazul principal: cineva copiază un fișier audio.
        """
        if event.is_directory:
            return  # ignorăm crearea de directoare

        file_path = Path(event.src_path)
        self._handle_new_file(file_path)

    def on_moved(self, event: FileMovedEvent) -> None:
        """
        Apelat când un fișier e MUTAT în inbox (rename/move).
        Cazul secundar: fișierul e mutat dintr-un alt director.
        Unele aplicații creează fișierul cu un nume temporar
        și îl redenumesc când e complet (ex: .tmp → .mp3).
        """
        if event.is_directory:
            return

        file_path = Path(event.dest_path)  # calea destinație (noul nume)
        self._handle_new_file(file_path)

    def _handle_new_file(self, file_path: Path) -> None:
        """
        Procesăm un fișier nou detectat.
        """
        # Ignorăm fișierele "hidden" (încep cu .)
        # Multe aplicații creează .tmp sau .part în timp ce copiază
        if file_path.name.startswith("."):
            return

        # Ignorăm fișierele din subfolder-ul /errors/
        if "errors" in file_path.parts:
            return

        # Evităm procesarea dublă a aceluiași fișier
        if str(file_path) in self._processing:
            logger.debug("already_processing", file=file_path.name)
            return

        self._processing.add(str(file_path))

        logger.info("file_detected", file=file_path.name)

        # Așteptăm puțin înainte de procesare
        # De ce? Dacă cineva copiază un fișier mare (1GB), watchdog
        # detectează imediat ce fișierul apare, dar el poate să nu fie
        # complet copiat. Așteptăm să se stabilizeze.
        self._wait_for_file_stable(file_path)

        # Programam procesarea pe event loop-ul principal fara blocare.
        # In felul acesta evitam deadlock-uri la startup si pastram pool-urile
        # async (ex: asyncpg) pe acelasi event loop.
        future = asyncio.run_coroutine_threadsafe(
            self.processor.process(file_path),
            self._event_loop,
        )

        def _on_done(done_future):
            try:
                done_future.result()
            except Exception as e:
                logger.error("processing_error", file=file_path.name, error=str(e))
            finally:
                # Scoatem din set indiferent de rezultat.
                self._processing.discard(str(file_path))

        future.add_done_callback(_on_done)

    def _wait_for_file_stable(
        self,
        file_path: Path,
        timeout_seconds: int = 300,  # max 5 minute pentru fișiere mari
        check_interval: float = 2.0,
    ) -> None:
        """
        Așteaptă ca fișierul să nu mai crească în dimensiune.
        Confirmă că copia s-a terminat.
        """
        last_size = -1
        elapsed = 0

        while elapsed < timeout_seconds:
            try:
                current_size = file_path.stat().st_size
            except FileNotFoundError:
                return  # fișierul a dispărut între timp

            if current_size == last_size and current_size > 0:
                # Dimensiunea nu s-a schimbat → copia e completă
                logger.debug(
                    "file_stable",
                    file=file_path.name,
                    size_mb=round(current_size / 1024 / 1024, 2)
                )
                return

            last_size = current_size
            time.sleep(check_interval)
            elapsed += check_interval

        logger.warning("file_stability_timeout", file=file_path.name)


class InboxWatcher:
    """
    Pornește și gestionează monitorizarea inbox-ului.
    """

    def __init__(self, processor: FileProcessor, event_loop: asyncio.AbstractEventLoop):
        self.processor = processor
        self._event_loop = event_loop
        self._observer: Optional[Observer] = None

    def start(self) -> None:
        """Pornește monitorizarea directorului inbox."""
        inbox_path = settings.inbox_path

        if not inbox_path.exists():
            inbox_path.mkdir(parents=True)

        handler = AudioFileHandler(self.processor, self._event_loop)

        self._observer = Observer()
        self._observer.schedule(
            handler,
            path=str(inbox_path),
            recursive=False,  # nu monitorizăm subdirectoare (excepție: /errors/)
        )
        self._observer.start()

        logger.info("watcher_started", inbox=str(inbox_path))

        # Procesăm fișierele existente la startup
        # (fișiere care au apărut cât serviciul era oprit)
        self._process_existing_files(handler)

    def stop(self) -> None:
        """Oprește monitorizarea elegant."""
        if self._observer:
            self._observer.stop()
            self._observer.join()
            logger.info("watcher_stopped")

    def _process_existing_files(self, handler: AudioFileHandler) -> None:
        """
        La startup, verificăm dacă există fișiere neprocessate în inbox.
        Aceasta gestionează cazul în care serviciul a fost oprit și
        au apărut fișiere noi între timp.
        """
        inbox_path = settings.inbox_path
        existing_files = [
            f for f in inbox_path.iterdir()
            if f.is_file() and not f.name.startswith(".")
        ]

        if existing_files:
            logger.info(
                "processing_existing_files",
                count=len(existing_files)
            )
            for file_path in existing_files:
                handler._handle_new_file(file_path)