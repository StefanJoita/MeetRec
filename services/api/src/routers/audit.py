# services/api/src/routers/audit.py
import csv
import io
import math
import uuid
from datetime import datetime
from typing import Optional, List, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select, func, cast, String
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.middleware.auth import get_current_admin
from src.models.audit_log import AuditLog, User

router = APIRouter(prefix="/audit-logs", tags=["audit"])


class AuditLogResponse(BaseModel):
    id: uuid.UUID
    timestamp: datetime
    user_id: Optional[uuid.UUID]
    user_ip: str
    user_username: Optional[str]
    user_email: Optional[str]
    action: str
    resource_type: Optional[str]
    resource_id: Optional[uuid.UUID]
    success: bool
    details: Optional[dict]

    model_config = ConfigDict(from_attributes=True)

    @field_validator('user_ip', mode='before')
    @classmethod
    def coerce_ip(cls, v: Any) -> str:
        return str(v)


class PaginatedAuditLogs(BaseModel):
    items: List[AuditLogResponse]
    total: int
    page: int
    page_size: int
    pages: int


@router.get("", response_model=PaginatedAuditLogs)
async def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(default=None, max_length=100),
    action: Optional[str] = Query(default=None),
    _: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * page_size

    base_stmt = (
        select(AuditLog)
        .outerjoin(User, AuditLog.user_id == User.id)
    )
    if action:
        base_stmt = base_stmt.where(AuditLog.action == action)
    if search:
        pattern = f"%{search}%"
        base_stmt = base_stmt.where(
            User.username.ilike(pattern)
            | User.email.ilike(pattern)
            | cast(AuditLog.user_ip, String).ilike(pattern)
        )

    total_result = await db.execute(select(func.count()).select_from(base_stmt.subquery()))
    total = total_result.scalar_one()

    stmt = (
        select(
            AuditLog,
            User.username.label("user_username"),
            User.email.label("user_email"),
        )
        .outerjoin(User, AuditLog.user_id == User.id)
        .order_by(AuditLog.timestamp.desc())
        .offset(offset)
        .limit(page_size)
    )
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            User.username.ilike(pattern)
            | User.email.ilike(pattern)
            | cast(AuditLog.user_ip, String).ilike(pattern)
        )
    result = await db.execute(stmt)
    rows = result.all()

    items = [
        AuditLogResponse(
            id=row.AuditLog.id,
            timestamp=row.AuditLog.timestamp,
            user_id=row.AuditLog.user_id,
            user_ip=str(row.AuditLog.user_ip),
            user_username=row.user_username,
            user_email=row.user_email,
            action=row.AuditLog.action,
            resource_type=row.AuditLog.resource_type,
            resource_id=row.AuditLog.resource_id,
            success=row.AuditLog.success,
            details=row.AuditLog.details,
        )
        for row in rows
    ]

    return PaginatedAuditLogs(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, math.ceil(total / page_size)),
    )


@router.get("/export", summary="Exportă jurnalul de audit ca CSV")
async def export_audit_logs_csv(
    action: Optional[str] = Query(default=None),
    _: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Descarcă toate intrările din jurnal ca fișier CSV. Max 10 000 rânduri."""
    stmt = (
        select(
            AuditLog,
            User.username.label("user_username"),
            User.email.label("user_email"),
        )
        .outerjoin(User, AuditLog.user_id == User.id)
        .order_by(AuditLog.timestamp.desc())
        .limit(10_000)
    )
    if action:
        stmt = stmt.where(AuditLog.action == action)

    result = await db.execute(stmt)
    rows = result.all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "timestamp", "action", "resource_type", "resource_id",
        "username", "email", "ip", "success", "details",
    ])
    for row in rows:
        log = row.AuditLog
        writer.writerow([
            log.timestamp.isoformat(),
            log.action,
            log.resource_type or "",
            str(log.resource_id) if log.resource_id else "",
            row.user_username or "",
            row.user_email or "",
            str(log.user_ip),
            "da" if log.success else "nu",
            str(log.details) if log.details else "",
        ])

    filename = f"audit-log-{datetime.utcnow().strftime('%Y%m%d-%H%M')}.csv"
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
