# services/search-indexer/src/listener.py
# ============================================================
# ChangeListener — ascultă NOTIFY din PostgreSQL
# ============================================================
# PostgreSQL LISTEN/NOTIFY = mecanism pub/sub nativ în DB.
#
# Cum funcționează:
#   - Triggerul 'transcript_completed_notify' din init.sql apelează
#     pg_notify('transcript_ready', transcript_id::text)
#     imediat după ce STT Worker setează status='completed'
#   - Noi facem LISTEN pe canalul 'transcript_ready'
#   - asyncpg ne cheamă callback-ul cu transcript_id ca payload
#   - Indexăm imediat acel transcript
#
# De ce LISTEN/NOTIFY și nu polling?
#   - Fără delay: indexarea începe în secunde după transcriere
#   - Zero CPU când nu e nimic de făcut
#   - O singură conexiune dedicată (nu ocupă pool-ul)
#
# IMPORTANT: LISTEN necesită o conexiune dedicată (nu din pool).
# asyncpg.create_pool() nu suportă LISTEN pe conexiunile pooled.

import asyncio
from typing import Optional

import asyncpg
import structlog

from src.config import settings
from src.indexer import TranscriptIndexer

logger = structlog.get_logger(__name__)


class ChangeListener:

    def __init__(self, indexer: TranscriptIndexer):
        self._indexer = indexer
        self._conn: Optional[asyncpg.Connection] = None
        self._running = False

    async def start(self) -> None:
        """
        Conectează o conexiune dedicată și ascultă notificările.
        Blochează până la stop().
        """
        self._running = True

        # Conexiune dedicată — nu din pool
        self._conn = await asyncpg.connect(dsn=settings.database_url)

        async def handle_notify(
            connection: asyncpg.Connection,
            pid: int,
            channel: str,
            payload: str,
        ) -> None:
            """
            Callback apelat de asyncpg când primim o notificare.
            payload = transcript_id (UUID ca string).
            Scheduleaza indexarea ca task independent — nu blocăm callback-ul.
            """
            logger.info("notify_received", transcript_id=payload, channel=channel)
            # create_task = rulează în background, callback-ul returnează imediat
            asyncio.create_task(self._safe_index(payload))

        await self._conn.add_listener(settings.notify_channel, handle_notify)
        logger.info("listening_started", channel=settings.notify_channel)

        # Așteptăm până la stop() — asyncpg procesează notificările automat
        while self._running:
            await asyncio.sleep(1)

        await self._conn.remove_listener(settings.notify_channel, handle_notify)
        await self._conn.close()
        logger.info("listening_stopped")

    def stop(self) -> None:
        """Oprește listener-ul după iterația curentă."""
        logger.info("listener_stop_requested")
        self._running = False

    async def _safe_index(self, transcript_id: str) -> None:
        """Wrapper care prinde excepțiile din indexare (nu vrem să crăpăm listener-ul)."""
        try:
            await self._indexer.index_transcript(transcript_id)
        except Exception as exc:
            logger.error(
                "indexing_failed_from_notify",
                transcript_id=transcript_id,
                error=str(exc),
            )
