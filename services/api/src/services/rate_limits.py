# services/api/src/services/rate_limits.py
# ============================================================
# Limitele anti-abuz pornite/oprite din Administrare → Setări
# ============================================================
# Setarea "rate_limit_enabled" (implicit RATE_LIMIT_ENABLED din .env, true)
# controlează:
#   - limitele per IP ale limiter-ului comun (src/limiter.py) → 429
#   - blocarea contului după parole greșite (src/services/login_lockout.py)
#
# Sursa unică la rulare e limiter.enabled. API-ul rulează într-un singur proces:
#   - la pornire și apoi la fiecare REFRESH_SECONDS se recitește setarea din DB
#   - la schimbarea din interfață (routers/admin.py) se aplică imediat
# Oprirea e gândită doar temporar (ex. scanare de vulnerabilități).
# ============================================================

import asyncio

import structlog

from src.database import session_factory
from src.limiter import limiter
from src.services import app_settings

logger = structlog.get_logger()

KEY = "rate_limit_enabled"
REFRESH_SECONDS = 30


def enabled() -> bool:
    return limiter.enabled


def apply(value) -> None:
    value = bool(value)
    if value != limiter.enabled:
        limiter.enabled = value
        logger.warning("rate_limits_enabled" if value else "rate_limits_disabled")


async def refresh() -> None:
    try:
        async with session_factory() as db:
            apply(await app_settings.effective_value(db, KEY))
    except Exception as e:   # DB indisponibilă: păstrăm starea curentă
        logger.warning("rate_limits_refresh_failed", error=str(e))


async def refresh_loop() -> None:
    while True:
        await refresh()
        await asyncio.sleep(REFRESH_SECONDS)
