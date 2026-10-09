# services/api/src/services/login_lockout.py
# ============================================================
# Blocare per username după eșecuri consecutive la login
# ============================================================
# Completează limita per IP de pe /auth/login (src/limiter.py): un atacator
# cu multe IP-uri tot nu poate încerca mai mult de MAX_FAILED_ATTEMPTS parole
# pentru același cont la fiecare LOCKOUT_SECONDS.
#
# Contorul e o cheie Redis cu TTL:
#   - fiecare eșec: INCR + EXPIRE (atomic, în tranzacție)
#   - la MAX_FAILED_ATTEMPTS eșecuri → contul e blocat până expiră cheia
#   - cât timp e blocat, încercările NU mai incrementează contorul
#     (blocarea durează exact LOCKOUT_SECONDS de la ultimul eșec)
#   - login reușit → cheia se șterge
#
# Se numără și username-urile inexistente: comportamentul e identic,
# ca răspunsul să nu dezvăluie dacă un cont există.
#
# Redis indisponibil → nu blocăm login-ul (limita per IP rămâne activă).
# ============================================================

from typing import Optional

import redis.asyncio as aioredis
import structlog
from redis.exceptions import RedisError

from src.config import settings

logger = structlog.get_logger()

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 15 * 60
_KEY_PREFIX = "login_failures:"

_redis_client: Optional[aioredis.Redis] = None


class LoginLockout:

    def __init__(self, redis: aioredis.Redis):
        self.redis = redis

    @staticmethod
    def _key(username: str) -> str:
        return f"{_KEY_PREFIX}{username}"

    async def is_locked(self, username: str) -> bool:
        try:
            count = await self.redis.get(self._key(username))
        except RedisError as e:
            logger.warning("login_lockout_redis_unavailable", error=str(e))
            return False
        return count is not None and int(count) >= MAX_FAILED_ATTEMPTS

    async def register_failure(self, username: str) -> bool:
        """Numără un eșec. Returnează True dacă acest eșec a blocat contul."""
        key = self._key(username)
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.incr(key)
                pipe.expire(key, LOCKOUT_SECONDS)
                count, _ = await pipe.execute()
        except RedisError as e:
            logger.warning("login_lockout_redis_unavailable", error=str(e))
            return False
        return int(count) == MAX_FAILED_ATTEMPTS

    async def reset(self, username: str) -> None:
        try:
            await self.redis.delete(self._key(username))
        except RedisError as e:
            logger.warning("login_lockout_redis_unavailable", error=str(e))


def get_login_lockout() -> LoginLockout:
    """FastAPI dependency. Clientul Redis (cu pool de conexiuni) e creat o singură dată."""
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return LoginLockout(_redis_client)
