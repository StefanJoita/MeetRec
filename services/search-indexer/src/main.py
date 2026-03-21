# services/search-indexer/src/main.py
# ============================================================
# Entry point pentru Search Indexer Service
# ============================================================
# Pornește 3 componente în paralel (asyncio.gather):
#   1. Listener  — LISTEN/NOTIFY pentru transcrieri noi
#   2. HTTP Server — /embed și /reindex endpoints
#   3. Bulk re-index la startup — indexează transcriptele existente
#
# Pattern lifecycle identic cu ceilalți workers.

import asyncio
import signal
import sys

import structlog
import uvicorn

from src.config import settings
from src.database import DatabaseClient
from src.embedder import Embedder
from src.indexer import TranscriptIndexer
from src.bulk_reindexer import bulk_reindex
from src.listener import ChangeListener
from src import http_server

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(__import__("logging"), settings.log_level, 20)
    ),
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger(__name__)


async def main() -> None:
    logger.info("search_indexer_starting")

    # ── 1. Conectăm DB ────────────────────────────────────
    db = DatabaseClient()
    await db.connect()

    # ── 2. Încărcăm modelul de embeddings ─────────────────
    embedder = Embedder()
    await embedder.load_model()

    # ── 3. Creăm indexer-ul ───────────────────────────────
    indexer = TranscriptIndexer(db.pool, embedder)

    # ── 4. Injectăm în HTTP server ────────────────────────
    http_server.init(embedder, db.pool, indexer)

    # ── 5. Listener NOTIFY ────────────────────────────────
    listener = ChangeListener(indexer)

    # ── Signal handlers ───────────────────────────────────
    loop = asyncio.get_running_loop()

    def handle_signal(sig: signal.Signals) -> None:
        logger.info("signal_received", signal=sig.name)
        listener.stop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: handle_signal(s))

    # ── 6. Bulk re-index la startup ───────────────────────
    logger.info("bulk_reindex_on_startup")
    await bulk_reindex(db.pool, indexer)

    # ── 7. Pornim HTTP server + listener în paralel ───────
    # uvicorn.Server folosit programatic (nu subprocess)
    uvi_config = uvicorn.Config(
        app=http_server.app,
        host="0.0.0.0",
        port=settings.http_port,
        log_level=settings.log_level.lower(),
        access_log=False,
    )
    uvi_server = uvicorn.Server(uvi_config)

    try:
        await asyncio.gather(
            uvi_server.serve(),
            listener.start(),
        )
    finally:
        await db.disconnect()
        logger.info("search_indexer_stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
