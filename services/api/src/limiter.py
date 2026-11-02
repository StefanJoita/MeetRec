# services/api/src/limiter.py
# ============================================================
# Rate Limiter — o singură instanță pentru toată aplicația
# ============================================================
# Cheia limitelor = IP-ul clientului (request.client.host).
#
# În producție API-ul e accesibil doar prin nginx, deci request.client.host
# ar fi mereu IP-ul nginx. Uvicorn rulează cu --proxy-headers și
# --forwarded-allow-ips=<subnetul frontend-network> (entrypoint.sh): pentru
# conexiunile venite din acel subnet, client.host devine IP-ul din
# X-Forwarded-For (setat de nginx la $remote_addr). Pentru orice altă sursă,
# X-Forwarded-For e ignorat.
#
# Folosire în routere:
#   from src.limiter import limiter
#   @limiter.limit("5/minute")
#
# NU adăugați limite pe /inbox/* — clientul desktop urcă multe segmente în
# paralel de pe același IP.
# ============================================================

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
