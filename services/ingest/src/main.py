# services/ingest/src/main.py
# ============================================================
# Entry Point — Pornește Ingest Service
# ============================================================
# Acest fișier:
# 1. Inițializează logging-ul
# 2. Creează toate dependențele
# 3. Pornește file watcher
# 4. Gestionează shutdown elegant (Ctrl+C, SIGTERM)
# ============================================================


import asyncio
import signal
import sys
 
from src.config import settings
from src.logger import setup_logging, get_logger
from src.validator import AudioValidator
from src.storage import StorageManager
from src.database import DatabaseClient
from src.publisher import JobPublisher
from src.processor import FileProcessor
from src.watcher import InboxWatcher
from src.session_watcher import SessionWatcher

logger=get_logger(__name__)

async def startup()-> tuple[DatabaseClient, InboxWatcher, SessionWatcher]:
    """Initializeaza toate componentele serviciului"""
    logger.info(
        "service_starting",
        inbox=str(settings.inbox_path),
        storage=str(settings.audio_storage_path),
        redis=settings.redis_url,
        )
    #Cream componentele in ordinea dependintelor
    #Database si Publisher trebuie sa fie gata inainte de Processor
    database=DatabaseClient()
    await database.connect()

    publisher = JobPublisher()

    #Verificam ca Redis e disponibil inainte de a continua
    if not publisher.health_check():
        logger.error("redis_unavailable", url=settings.redis_url)
        sys.exit(1)

    #Asamblam procesorul cu toate dependintele sale
    processor=FileProcessor(
        validator=AudioValidator(),
        storage=StorageManager(),
        publisher=publisher,
        database=database,
    )

    #Pornim watcher-ul care monitorizeaza inbox-ul
    watcher=InboxWatcher(processor=processor, event_loop=asyncio.get_running_loop())
    watcher.start()

    # Pornim Session Watcher — lansează transcrierea sesiunilor complete după timeout
    session_watcher = SessionWatcher(database=database, publisher=publisher)
    asyncio.create_task(session_watcher.start())

    logger.info("service_started")
    return database, watcher, session_watcher

async def shutdown(database: DatabaseClient, watcher: InboxWatcher, session_watcher: SessionWatcher) -> None:
    """Opreste serviciul elegant: inchide conexiunile, watcher-ul, etc"""
    logger.info("service_stopping")
    watcher.stop()
    session_watcher.stop()
    await database.disconnect()
    logger.info("service_stopped")

async def main()-> None:
    """Functia principala async care porneste serviciul si asteapta semnale de shutdown"""
    #configuram loggingul primul
    setup_logging()
    database, watcher, session_watcher = await startup()

    #Event pentru shutdown ( setat de signal handlers)
    stop_event=asyncio.Event()
    def handle_shutdown(sig_name: str):
        """Handler pentru SIGTERM și SIGINT (Ctrl+C)."""
        logger.info("shutdown_signal_received", signal=sig_name)
        stop_event.set()
 
    # Înregistrăm signal handlers
    # SIGTERM: trimis de Docker la `docker stop`
    # SIGINT: trimis de Ctrl+C în terminal
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda s=sig.name: handle_shutdown(s)
        )
 
    logger.info("waiting_for_files", inbox=str(settings.inbox_path))
 
    # Rulăm până primim semnal de oprire
    await stop_event.wait()
 
    # Cleanup
    await shutdown(database, watcher, session_watcher)

if __name__ =="__main__":
       # asyncio.run() = pornește event loop-ul Python async
    # Event loop 101: permite rularea mai multor operații "simultan"
    # fără thread-uri multiple (cooperative multitasking)
    asyncio.run(main())
