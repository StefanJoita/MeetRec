# services/api/src/routers/audit.py
import csv
import io
import json
import math
import uuid
from datetime import datetime
from typing import Optional, List, Any, Dict, Tuple

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import and_, select, func, cast, or_, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from src.database import get_db
from src.middleware.auth import get_current_admin
from src.models.audit_log import AuditLog, User
from src.models.recording import Recording
from src.models.transcript import Transcript
from src.services.audit_describe import describe
from src.services.export_naming import attachment_headers, export_filename

router = APIRouter(prefix="/audit-logs", tags=["audit"])

# resource_id = id-ul înregistrării pentru aceste tipuri
RECORDING_TYPES = ("recording", "recording_participant", "recording_speaker_mapping")

# Filtrul „Resursă” din interfață → tipurile din jurnal
RESOURCE_GROUPS: Dict[str, Tuple[str, ...]] = {
    "recording": RECORDING_TYPES + ("transcript", "recordings_list"),
    "user": ("user", "users_list"),
    "app_setting": ("app_setting",),
    "audit_logs": ("audit_logs",),
    "backup": ("backup",),
}


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
    resource_name: Optional[str] = None      # numele de la momentul acțiunii (sau cel actual, la intrări vechi)
    resource_deleted: bool = False           # resursa nu mai există
    recording_id: Optional[uuid.UUID] = None # pentru link, dacă înregistrarea încă există
    description: Optional[str] = None

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


# ── Filtre comune (listă + CSV) ──────────────────────────────

def _filtered(stmt, search: Optional[str], action: Optional[str], resource: Optional[str]):
    """Aplică filtrele; `stmt` trebuie să aibă deja join-ul cu User (autorul)."""
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if resource:
        stmt = stmt.where(AuditLog.resource_type.in_(RESOURCE_GROUPS.get(resource, (resource,))))
    if search:
        pattern = f"%{search}%"
        target_user = aliased(User)
        stmt = (
            stmt
            # numele actual, pentru intrările scrise înainte de details.resource_name
            .outerjoin(Recording, and_(AuditLog.resource_id == Recording.id,
                                       AuditLog.resource_type.in_(RECORDING_TYPES)))
            .outerjoin(target_user, and_(AuditLog.resource_id == target_user.id,
                                         AuditLog.resource_type == "user"))
            .where(or_(
                User.username.ilike(pattern),
                User.email.ilike(pattern),
                cast(AuditLog.user_ip, String).ilike(pattern),
                AuditLog.details["resource_name"].astext.ilike(pattern),
                AuditLog.details["title"].astext.ilike(pattern),
                AuditLog.details["participant"].astext.ilike(pattern),
                AuditLog.details["username"].astext.ilike(pattern),
                Recording.title.ilike(pattern),
                target_user.username.ilike(pattern),
                target_user.full_name.ilike(pattern),
            ))
        )
    return stmt


def _rows_stmt():
    return (
        select(AuditLog, User.username.label("user_username"), User.email.label("user_email"))
        .outerjoin(User, AuditLog.user_id == User.id)
    )


# ── Numele resurselor ────────────────────────────────────────

async def _current_resources(db: AsyncSession, logs: List[AuditLog]) -> Dict[Tuple[str, uuid.UUID], Tuple[str, Optional[uuid.UUID]]]:
    """{(tip, id): (nume actual, recording_id)} pentru resursele care încă există."""
    ids: Dict[str, set] = {"recording": set(), "transcript": set(), "user": set()}
    for log in logs:
        if log.resource_id is None:
            continue
        kind = "recording" if log.resource_type in RECORDING_TYPES else log.resource_type
        if kind in ids:
            ids[kind].add(log.resource_id)

    # Încărcările din API se fac înainte ca Ingest să creeze înregistrarea → legătura prin sha256
    hashes = {log.details["sha256"] for log in logs
              if log.resource_id is None and log.action == "UPLOAD" and (log.details or {}).get("sha256")}

    found: Dict[Tuple[str, Any], Tuple[str, Optional[uuid.UUID]]] = {}
    if hashes:
        rows = await db.execute(select(Recording.file_hash_sha256, Recording.id, Recording.title)
                                .where(Recording.file_hash_sha256.in_(hashes)))
        found.update({("sha256", h): (title, rid) for h, rid, title in rows.all()})
    if ids["recording"]:
        rows = await db.execute(select(Recording.id, Recording.title).where(Recording.id.in_(ids["recording"])))
        found.update({("recording", rid): (title, rid) for rid, title in rows.all()})
    if ids["transcript"]:
        rows = await db.execute(
            select(Transcript.id, Recording.id, Recording.title)
            .join(Recording, Recording.id == Transcript.recording_id)
            .where(Transcript.id.in_(ids["transcript"]))
        )
        found.update({("transcript", tid): (title, rid) for tid, rid, title in rows.all()})
    if ids["user"]:
        rows = await db.execute(select(User.id, User.username, User.full_name).where(User.id.in_(ids["user"])))
        found.update({("user", uid): (f"{full} ({name})" if full else name, None) for uid, name, full in rows.all()})
    return found


def _to_response(row, current: Dict) -> AuditLogResponse:
    log = row.AuditLog
    details = log.details or {}
    kind = "recording" if log.resource_type in RECORDING_TYPES else log.resource_type
    resolvable = log.resource_id is not None and kind in ("recording", "transcript", "user")
    existing = current.get((kind, log.resource_id)) if resolvable else current.get(("sha256", details.get("sha256")))
    return AuditLogResponse(
        id=log.id,
        timestamp=log.timestamp,
        user_id=log.user_id,
        user_ip=str(log.user_ip),
        user_username=row.user_username,
        user_email=row.user_email,
        action=log.action,
        resource_type=log.resource_type,
        resource_id=log.resource_id,
        success=log.success,
        details=details,
        resource_name=details.get("resource_name") or details.get("title") or (existing[0] if existing else None)
                      or details.get("username"),     # autentificare eșuată: utilizatorul încercat
        resource_deleted=resolvable and existing is None,
        recording_id=existing[1] if existing else None,
        description=describe(log.action, log.resource_type, details),
    )


# ── Endpoint-uri ─────────────────────────────────────────────

@router.get("", response_model=PaginatedAuditLogs)
async def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(default=None, max_length=100),
    action: Optional[str] = Query(default=None),
    resource: Optional[str] = Query(default=None, description="recording | user | app_setting | audit_logs | backup"),
    _: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = _filtered(_rows_stmt(), search, action, resource)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()

    rows = (await db.execute(
        stmt.order_by(AuditLog.timestamp.desc()).offset((page - 1) * page_size).limit(page_size)
    )).all()
    current = await _current_resources(db, [r.AuditLog for r in rows])

    return PaginatedAuditLogs(
        items=[_to_response(r, current) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, math.ceil(total / page_size)),
    )


@router.get("/export", summary="Exportă jurnalul de audit ca CSV")
async def export_audit_logs_csv(
    search: Optional[str] = Query(default=None, max_length=100),
    action: Optional[str] = Query(default=None),
    resource: Optional[str] = Query(default=None),
    _: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Descarcă intrările din jurnal (cu filtrele din interfață) ca fișier CSV. Max 10 000 rânduri."""
    rows = (await db.execute(
        _filtered(_rows_stmt(), search, action, resource)
        .order_by(AuditLog.timestamp.desc())
        .limit(10_000)
    )).all()
    current = await _current_resources(db, [r.AuditLog for r in rows])

    output = io.StringIO()
    output.write("﻿")   # BOM: Excel deschide corect diacriticele
    writer = csv.writer(output)
    writer.writerow([
        "timestamp", "action", "resource_type", "resource_id", "resource_name", "resource_deleted",
        "description", "username", "email", "ip", "success", "details",
    ])
    for row in rows:
        item = _to_response(row, current)
        writer.writerow([
            item.timestamp.isoformat(),
            item.action,
            item.resource_type or "",
            str(item.resource_id) if item.resource_id else "",
            item.resource_name or "",
            "da" if item.resource_deleted else "",
            item.description or "",
            item.user_username or "",
            item.user_email or "",
            item.user_ip,
            "da" if item.success else "nu",
            json.dumps(item.details, ensure_ascii=False) if item.details else "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers=attachment_headers(export_filename("Jurnal audit", "csv")),
    )
