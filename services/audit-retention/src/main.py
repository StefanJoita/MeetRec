# services/audit-retention/src/main.py
# Entry point pentru Audit & Retention Service.
# Același pattern de lifecycle ca ingest/main.py și stt-worker/main.py:
#   - conectăm DB la startup
#   - handleăm SIGTERM/SIGINT pentru oprire curată
#   - pornim scheduler-ul

import asyncio
import signal
import sys

import structlog

from src.config import settings
from src.database import DatabaseClient
from src.retention_scheduler import RetentionScheduler

# Configurare structlog — output JSON pentru Loki
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
    logger.info("audit_retention_starting",
                retention_days=settings.retention_days,
                audit_retention_days=settings.audit_log_retention_days)

    db = DatabaseClient()
    await db.connect()

    scheduler = RetentionScheduler(db)

    # ── Signal handlers pentru oprire curată ──────────────────────────────
    loop = asyncio.get_running_loop()

    def handle_signal(sig: signal.Signals) -> None:
        logger.info("signal_received", signal=sig.name)
        scheduler.stop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: handle_signal(s))

    try:
        await scheduler.start()
    finally:
        await db.disconnect()
        logger.info("audit_retention_stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
