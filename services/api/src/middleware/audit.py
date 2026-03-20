# services/api/src/middleware/audit.py
import uuid
from typing import Optional
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.audit_log import AuditLog


def _extract_user_id(request: Request) -> Optional[uuid.UUID]:
    """
    Extrage user_id din JWT-ul din request.
    Import-ul decode_token e local pentru a evita importul circular
    (auth.py nu importă din audit.py, deci e sigur).
    """
    from src.middleware.auth import decode_token

    # Tokenul vine fie din header (Authorization: Bearer ...) fie din query param
    raw_token: Optional[str] = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        raw_token = auth_header[7:]
    else:
        # Fallback: token ca query param (folosit de /audio stream)
        raw_token = request.query_params.get("token")

    if not raw_token:
        return None

    user_id_str = decode_token(raw_token)
    if not user_id_str:
        return None

    try:
        return uuid.UUID(user_id_str)
    except ValueError:
        return None


async def log_audit(
    request: Request,
    db: AsyncSession,
    action: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[uuid.UUID] = None,
    details: Optional[dict] = None,
    success: bool = True,
) -> None:
    """
    Loghează o acțiune în tabela audit_logs.
    Apelat explicit în fiecare router după operații importante.

    Primește sesiunea DB ca parametru explicit (nu din request.state)
    pentru a garanta că log-ul se scrie în aceeași tranzacție.
    """
    # Extragem IP-ul real (Nginx pune IP-ul original în X-Real-IP)
    ip = (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else None)
        or "unknown"
    )

    log_entry = AuditLog(
        user_id=_extract_user_id(request),
        user_ip=ip,
        user_agent=request.headers.get("User-Agent"),
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details or {},
        success=success,
    )

    db.add(log_entry)
    # commit-ul e gestionat de get_db() după yield — nu facem commit aici
