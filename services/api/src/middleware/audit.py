# services/api/src/middleware/audit.py
import uuid
from typing import Optional
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.audit_log import AuditLog


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
