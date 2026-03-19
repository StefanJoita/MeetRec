# services/api/src/routers/audit.py
import math
import uuid
from datetime import datetime
from typing import Optional, List, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select, func
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
    action: str
    resource_type: Optional[str]
    resource_id: Optional[uuid.UUID]
    success: bool

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
    _: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * page_size

    total_result = await db.execute(select(func.count()).select_from(AuditLog))
    total = total_result.scalar_one()

    rows = await db.execute(
        select(AuditLog).order_by(AuditLog.timestamp.desc()).offset(offset).limit(page_size)
    )
    items = rows.scalars().all()

    return PaginatedAuditLogs(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, math.ceil(total / page_size)),
    )
