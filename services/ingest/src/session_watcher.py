# services/ingest/src/session_watcher.py
# ============================================================
# Session Watcher — lansează transcrierea sesiunilor complete
# ============================================================
# Problema de rezolvat:
#   Clientul desktop trimite o ședință de 1h în bucăți de 10min.
#   Fiecare bucată ajunge separat — serverul nu știe când s-a terminat
#   (clientul nu trimite semnal explicit de "stop").
#
# Soluție — timeout:
#   Dacă nu a sosit niciun segment nou pentru SESSION_TIMEOUT secunde,
#   considerăm că sesiunea e completă și lansăm transcrierea.
#
# Flow:
#   Ingest primește segment → salvează în DB → actualizează last_segment_at
#   Session Watcher (la fiecare WATCHER_INTERVAL secunde):
#     → caută sesiuni cu last_segment_at < NOW() - SESSION_TIMEOUT
#     → marchează sesiunea ca 'transcribing' (previne dublă-lansare)
#     → publică UN JOB în Redis cu session_mode=True
#   STT Worker primește jobul:
#     → interoghează DB pentru toate segmentele sesiunii
#     → concatenează audio-ul în ordinea segment_index
#     → transcrie fișierul concatenat o singură dată cu Whisper
#
# De ce timeout și nu semnal explicit?
#   Cerința clientului: nu există semnal de "sesiune terminată".
#   Timeout-ul de 120s este suficient pentru:
#     - Retry-uri de rețea ale clientului (max 3 × 30s = 90s)
#     - Variații de latență la upload (~27MB per segment)
# ============================================================

import asyncio

import structlog

from src.config import settings
from src.database import DatabaseClient
from src.publisher import JobPublisher

logger = structlog.get_logger(__name__)


class SessionWatcher:
    """
    Task async care rulează în background și lansează transcrierea
    sesiunilor multi-segment după ce timeout-ul a expirat.
    """

    def __init__(self, database: DatabaseClient, publisher: JobPublisher):
        self._db = database
        self._publisher = publisher
        self._running = False

    async def start(self) -> None:
        """Pornește watcher-ul. Blochează până la stop()."""
        self._running = True
        logger.info(
            "session_watcher_started",
            timeout_seconds=settings.session_timeout_seconds,
            interval_seconds=settings.session_watcher_interval_seconds,
        )

        while self._running:
            await asyncio.sleep(settings.session_watcher_interval_seconds)
            if self._running:
                await self._run_once()

        logger.info("session_watcher_stopped")

    def stop(self) -> None:
        """Oprește watcher-ul după iterația curentă."""
        self._running = False

    async def _run_once(self) -> None:
        """
        O iterație: caută sesiunile expirate și publică joburi de transcriere.

        Ordinea operațiilor este critică pentru idempotență:
        1. mark_session_dispatched → status='transcribing' (exclude din query viitor)
        2. publish_session_job → adaugă în Redis
        Dacă (2) eșuează, sesiunea rămâne în 'transcribing' fără job Redis —
        recuperabilă manual. E preferabil față de dublă-publicare (transcript duplicat).
        """
        try:
            expired_ids = await self._db.find_expired_sessions(
                settings.session_timeout_seconds
            )
        except Exception as e:
            logger.error("session_watcher_query_failed", error=str(e))
            return

        if not expired_ids:
            return

        logger.info("sessions_ready_for_transcription", count=len(expired_ids))

        for recording_id in expired_ids:
            try:
                # Pas 1: marchează ÎNAINTE de publish (idempotență)
                await self._db.mark_session_dispatched(recording_id)

                # Pas 2: publică jobul în Redis
                self._publisher.publish_session_job(
                    recording_id=recording_id,
                    language_hint="ro",
                )

                logger.info("session_job_dispatched", recording_id=recording_id)

            except Exception as e:
                logger.error(
                    "session_dispatch_failed",
                    recording_id=recording_id,
                    error=str(e),
                )
                # Continuăm cu celelalte sesiuni — nu oprim la prima eroare
