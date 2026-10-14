# services/api/src/routers/admin.py
# ============================================================
# Administrare: setări de funcționare și starea sistemului
# ============================================================
#   GET    /admin/settings          → toate setările, cu valoarea efectivă și sursa
#   PUT    /admin/settings/{key}    → setează din interfață (validat, auditat)
#   DELETE /admin/settings/{key}    → revine la valoarea din .env
#   GET    /admin/system            → versiune, worker-e, coadă, disc, eșecuri recente
#   GET    /config/upload           → limita de upload (pentru orice utilizator autentificat)
# ============================================================

import json
import os
import shutil
from datetime import datetime
from typing import Any, Dict, List, Optional

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import get_db
from src.middleware.audit import log_audit
from src.middleware.auth import get_current_admin, get_current_user
from src.models.audit_log import User
from src.models.recording import Recording
from src.services import app_settings as registry

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])
config_router = APIRouter(prefix="/config", tags=["config"])

# Cheia Redis în care fiecare stt-worker își publică starea (src/consumer.py)
WORKER_STATUS_PREFIX = "stt_worker:status:"


# ── Scheme ───────────────────────────────────────────────────

class SettingResponse(BaseModel):
    key: str
    group: str
    label: str
    description: str
    applies: str
    type: str
    min: Optional[int]
    max: Optional[int]
    unit: Optional[str]
    value: Any
    env_value: Any
    source: str                  # "interfata" | "env"
    updated_at: Optional[datetime]
    updated_by: Optional[str]


class SettingUpdate(BaseModel):
    value: Any


class UploadConfig(BaseModel):
    max_file_size_bytes: int


# ── Setări ───────────────────────────────────────────────────

async def _list_settings(db: AsyncSession) -> List[SettingResponse]:
    overridden = await registry.overrides(db)
    user_ids = {r.updated_by for r in overridden.values() if r.updated_by}
    usernames: Dict[Any, str] = {}
    if user_ids:
        rows = await db.execute(select(User.id, User.username).where(User.id.in_(user_ids)))
        usernames = {uid: name for uid, name in rows.all()}

    result = []
    for d in registry.SETTINGS:
        row = overridden.get(d.key)
        result.append(SettingResponse(
            key=d.key, group=d.group, label=d.label, description=d.description,
            applies=d.applies, type=d.type, min=d.min, max=d.max, unit=d.unit,
            value=row.value if row else registry.env_value(d),
            env_value=registry.env_value(d),
            source="interfata" if row else "env",
            updated_at=row.updated_at if row else None,
            updated_by=usernames.get(row.updated_by) if row and row.updated_by else None,
        ))
    return result


def _definition(key: str) -> registry.SettingDef:
    d = registry.BY_KEY.get(key)
    if d is None:
        raise HTTPException(status_code=404, detail="Setare necunoscută.")
    return d


@router.get("/settings", response_model=List[SettingResponse], summary="Setările de funcționare")
async def list_settings(
    _: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    return await _list_settings(db)


@router.put("/settings/{key}", response_model=List[SettingResponse], summary="Schimbă o setare")
async def update_setting(
    key: str,
    body: SettingUpdate,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    _definition(key)
    old = await registry.effective_value(db, key)
    try:
        new = await registry.set_value(db, key, body.value, admin.id)
    except registry.SettingValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    await log_audit(request, db, action="UPDATE", resource_type="app_setting",
                    details={"key": key, "old": old, "new": new})
    await db.commit()
    logger.info("app_setting_updated", key=key, old=old, new=new, by=admin.username)
    return await _list_settings(db)


@router.delete("/settings/{key}", response_model=List[SettingResponse],
               summary="Revine la valoarea din .env")
async def reset_setting(
    key: str,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    d = _definition(key)
    old = await registry.effective_value(db, key)
    try:
        await registry.reset_value(db, key)
    except registry.SettingValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    new = registry.env_value(d)
    await log_audit(request, db, action="UPDATE", resource_type="app_setting",
                    details={"key": key, "old": old, "new": new, "reset": True})
    await db.commit()
    logger.info("app_setting_reset", key=key, old=old, new=new, by=admin.username)
    return await _list_settings(db)


@config_router.get("/upload", response_model=UploadConfig, summary="Limita de încărcare")
async def upload_config(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    mb = await registry.effective_value(db, "max_file_size_mb")
    return UploadConfig(max_file_size_bytes=mb * registry.MIB)


# ── Starea sistemului ────────────────────────────────────────

async def _redis_status() -> Dict[str, Any]:
    """Worker-ele active și lungimea cozii. Redis indisponibil → raportat, nu eroare."""
    queue = settings.redis_transcription_queue
    r = aioredis.from_url(settings.redis_url, decode_responses=True, socket_timeout=3)
    try:
        workers = []
        async for key in r.scan_iter(match=f"{WORKER_STATUS_PREFIX}*"):
            raw = await r.get(key)
            if raw:
                try:
                    workers.append(json.loads(raw))
                except ValueError:
                    pass
        processing = 0
        async for key in r.scan_iter(match=f"{queue}:processing:*"):
            processing += await r.llen(key)
        return {
            "available": True,
            "queued": await r.llen(queue),
            "processing": processing,
            "workers": sorted(workers, key=lambda w: w.get("worker_id", "")),
        }
    except Exception as e:
        logger.warning("admin_system_redis_error", error=str(e))
        return {"available": False, "queued": None, "processing": None, "workers": []}
    finally:
        await r.aclose()


def _disk() -> Optional[Dict[str, int]]:
    try:
        usage = shutil.disk_usage(settings.audio_storage_path)
    except OSError:
        return None
    return {"total_bytes": usage.total, "used_bytes": usage.used, "free_bytes": usage.free}


@router.get("/system", summary="Starea sistemului")
async def system_status(
    _: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    counts = dict((await db.execute(
        select(Recording.status, func.count()).group_by(Recording.status)
    )).all())
    failed = (await db.execute(
        select(Recording.id, Recording.title, Recording.error_message, Recording.updated_at)
        .where(Recording.status == "failed")
        .order_by(Recording.updated_at.desc())
        .limit(5)
    )).all()

    return {
        "version": os.environ.get("MEETREC_VERSION") or None,
        "whisper_model_configured": os.environ.get("WHISPER_MODEL") or None,
        "queue": await _redis_status(),
        "disk": _disk(),
        "recordings_by_status": {str(k.value if hasattr(k, "value") else k): v for k, v in counts.items()},
        "recent_failures": [
            {"id": str(f.id), "title": f.title, "error_message": f.error_message,
             "updated_at": f.updated_at.isoformat() if f.updated_at else None}
            for f in failed
        ],
    }
