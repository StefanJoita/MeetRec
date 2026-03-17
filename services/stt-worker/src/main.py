# services/stt-worker/src/main.py
# ============================================================
# Entry Point — Pornește STT Worker
# ============================================================
# Ordinea de startup este critică:
#   1. DB connect     — trebuie gata înainte de primul job
#   2. Whisper load   — pasul lent (5-30s), trebuie gata înainte de consumer
#   3. Consumer start — blochează până la shutdown (SIGTERM/SIGINT)
#
# Pattern signal handler (identic cu services/ingest/src/main.py):
#   - asyncio.Event() ca "steag" pentru shutdown
#   - handle_shutdown() îl setează când vine SIGTERM
#   - await stop_event.wait() blochează main() până la semnal
#   - după semnal: consumer.stop() → așteptăm max 30s să termine jobul curent
# ============================================================

import asyncio
import signal
import sys

from src.config import settings
from src.consumer import JobConsumer
from src.language_detector import LanguageDetector
from src.postprocessor import PostProcessor
from src.transcriber import WhisperTranscriber
from src.uploader import DatabaseUploader

import structlog

logger = structlog.get_logger(__name__)


async def startup() -> tuple[DatabaseUploader, JobConsumer]:
    """
    Inițializează toate componentele în ordinea dependențelor.

    DE CE această ordine?
    1. DB: consumer-ul va scrie în DB la primul job → trebuie gata
    2. Whisper: consumer-ul transcrie imediat ce primește job → trebuie gata
    3. Consumer: blochează → pornit ultimul
    """
    logger.info(
        "service_starting",
        model=settings.whisper_model,
        queue=settings.redis_transcription_queue,
    )

    # ── 1. Conectăm la PostgreSQL ─────────────────────────────
    uploader = DatabaseUploader()
    await uploader.connect()

    # ── 2. Încărcăm modelul Whisper ───────────────────────────
    # Pasul CEL MAI LENT: 5-30 secunde, descarcă ~1.5GB prima dată.
    # Logăm explicit pentru că Docker healthcheck-ul va considera
    # containerul "unhealthy" dacă nu răspunde în timp util.
    logger.info("model_loading_started", model=settings.whisper_model)
    transcriber = WhisperTranscriber()
    await transcriber.load_model()
    logger.info("model_loading_done")

    # ── 3. Creăm celelalte componente ─────────────────────────
    # LanguageDetector primește modelul deja încărcat — fără RAM suplimentar
    detector = LanguageDetector(model=transcriber._model)
    postprocessor = PostProcessor()

    # ── 4. Asamblăm consumer-ul ───────────────────────────────
    consumer = JobConsumer(
        transcriber=transcriber,
        uploader=uploader,
        detector=detector,
        postprocessor=postprocessor,
    )

    logger.info("service_started")
    return uploader, consumer


async def shutdown(uploader: DatabaseUploader, consumer: JobConsumer) -> None:
    """
    Oprire elegantă: semnalăm consumer-ul, așteptăm să termine, închidem DB.

    consumer.stop() setează _running=False.
    Consumer-ul termină jobul curent (dacă e în mijloc de transcriere)
    și iese din loop după max 30s (timeout-ul BRPOP).
    Abia apoi închidem DB — altfel save_results() ar eșua.
    """
    logger.info("service_stopping")
    consumer.stop()
    # Nu avem un "await consumer.wait_done()" — loop-ul se oprește singur
    # după ce _running=False și BRPOP timeout-ul expiră.
    # uploader.disconnect() se apelează după ce main() revine din await consumer.start()
    await uploader.disconnect()
    logger.info("service_stopped")


async def main() -> None:
    """
    Funcția principală: pornește serviciul și așteaptă SIGTERM/SIGINT.
    """
    # Logging înainte de orice altceva
    # (importăm structlog direct pentru că logger.py din ingest nu e copiat)
    import structlog
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.add_log_level,
            structlog.processors.JSONRenderer(),
        ]
    )

    uploader, consumer = await startup()

    # ── Signal handlers ───────────────────────────────────────
    # asyncio.Event() = un "steag" async
    # stop_event.set() → trezește await stop_event.wait()
    stop_event = asyncio.Event()

    def handle_shutdown(sig_name: str):
        """Apelat de OS când primim SIGTERM sau SIGINT (Ctrl+C)."""
        logger.info("shutdown_signal_received", signal=sig_name)
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda s=sig.name: handle_shutdown(s),
        )

    # ── Consumer loop în background task ─────────────────────
    # consumer.start() blochează indefinit → îl rulăm ca Task asyncio
    # pentru că trebuie să așteptăm și stop_event.wait() simultan
    consumer_task = asyncio.create_task(consumer.start())

    logger.info("waiting_for_jobs", queue=settings.redis_transcription_queue)

    # Așteptăm semnalul de shutdown
    await stop_event.wait()

    # Shutdown elegant
    await shutdown(uploader, consumer)

    # Așteptăm terminarea task-ului consumer (max ~30s)
    try:
        await asyncio.wait_for(consumer_task, timeout=35)
    except asyncio.TimeoutError:
        logger.warning("consumer_task_timeout")
        consumer_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
