# services/api/src/routers/admin.py
# ============================================================
# Administrare: setări de funcționare și starea sistemului
# ============================================================
#   GET    /admin/settings          → toate setările, cu valoarea efectivă și sursa
#   PUT    /admin/settings/{key}    → setează din interfață (validat, auditat)
#   DELETE /admin/settings/{key}    → revine la valoarea din .env
#   GET    /admin/system            → versiune, worker-e, coadă, disc, eșecuri recente
#   GET    /admin/processing        → durata transcrierii pe înregistrare și pe etape
#   GET    /admin/queue             → coada de transcriere: în lucru (etapă, procent) și în așteptare
#   POST   /admin/queue/{id}/cancel     → scoate din coadă / oprește transcrierea în curs
#   POST   /admin/queue/{id}/prioritize → mută înregistrarea prima în coadă
#   GET    /config/upload           → limita de upload (pentru orice utilizator autentificat)
# ============================================================

import json
import math
import os
import shutil
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import Float, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import get_db
from src.middleware.audit import log_audit
from src.middleware.auth import get_current_admin, get_current_user
from src.models.audit_log import User
from src.models.recording import Recording, RecordingStatus
from src.models.transcript import Transcript, TranscriptStatus
from src.services import app_settings as registry
from src.services.queue_service import WORKER_STATUS_PREFIX, QueueService, get_queue_service

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])
config_router = APIRouter(prefix="/config", tags=["config"])


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


class ProcessingItem(BaseModel):
    recording_id: str
    title: str
    completed_at: Optional[datetime]
    model_used: Optional[str]
    audio_sec: Optional[int]
    processing_sec: int
    ratio: Optional[float]           # processing_sec / audio_sec (sub 1 = mai repede ca timpul real)
    transcription_sec: Optional[float]
    alignment_sec: Optional[float]
    diarization_sec: Optional[float]
    diarization_parallel: bool


class ProcessingSummary(BaseModel):
    count: int
    audio_sec: int
    processing_sec: int
    ratio: Optional[float]           # pe total: timp de procesare / durată audio


class ProcessingPage(BaseModel):
    items: List[ProcessingItem]
    total: int
    page: int
    page_size: int
    pages: int
    summary: ProcessingSummary


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


async def _search_index_status() -> Dict[str, Any]:
    """Starea search-indexer: modelul și câte segmente așteaptă indexarea."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{settings.search_indexer_url}/health")
            resp.raise_for_status()
            body = resp.json()
        return {"available": True, "model": body.get("model"), "pending_segments": body.get("pending_segments")}
    except Exception as e:
        logger.warning("admin_system_search_indexer_error", error=str(e))
        return {"available": False, "model": None, "pending_segments": None}


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
        "search_index": await _search_index_status(),
        "disk": _disk(),
        "recordings_by_status": {str(k.value if hasattr(k, "value") else k): v for k, v in counts.items()},
        "recent_failures": [
            {"id": str(f.id), "title": f.title, "error_message": f.error_message,
             "updated_at": f.updated_at.isoformat() if f.updated_at else None}
            for f in failed
        ],
    }


# ── Durata procesării ────────────────────────────────────────

def _ratio(processing: Optional[float], audio: Optional[float]) -> Optional[float]:
    return round(processing / audio, 2) if processing and audio else None


def _num(value) -> Optional[float]:
    return float(value) if value is not None else None


@router.get("/processing", response_model=ProcessingPage, summary="Durata procesării pe înregistrare")
async def processing_times(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort: str = Query("recent", pattern="^(recent|slowest)$"),
    _: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Transcrierile finalizate, cu durata totală și pe etape (cele mai noi sau cele mai lente)."""
    done = (Transcript.status == TranscriptStatus.COMPLETED.value,
            Transcript.processing_time_sec.isnot(None))
    ratio = (cast(Transcript.processing_time_sec, Float)
             / func.nullif(Recording.duration_seconds, 0))
    order = ((ratio.desc().nulls_last(), Transcript.completed_at.desc()) if sort == "slowest"
             else (Transcript.completed_at.desc().nulls_last(),))

    totals = (await db.execute(
        select(func.count(), func.coalesce(func.sum(Recording.duration_seconds), 0),
               func.coalesce(func.sum(Transcript.processing_time_sec), 0))
        .select_from(Transcript).join(Recording, Recording.id == Transcript.recording_id)
        .where(*done)
    )).one()
    count, audio_total, processing_total = totals

    rows = (await db.execute(
        select(Recording.id, Recording.title, Recording.duration_seconds,
               Transcript.completed_at, Transcript.model_used, Transcript.processing_time_sec,
               Transcript.transcription_sec, Transcript.alignment_sec,
               Transcript.diarization_sec, Transcript.diarization_parallel)
        .select_from(Transcript).join(Recording, Recording.id == Transcript.recording_id)
        .where(*done)
        .order_by(*order)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )).all()

    return ProcessingPage(
        items=[ProcessingItem(
            recording_id=str(r.id), title=r.title, completed_at=r.completed_at,
            model_used=r.model_used, audio_sec=r.duration_seconds,
            processing_sec=r.processing_time_sec,
            ratio=_ratio(r.processing_time_sec, r.duration_seconds),
            transcription_sec=_num(r.transcription_sec), alignment_sec=_num(r.alignment_sec),
            diarization_sec=_num(r.diarization_sec),
            diarization_parallel=bool(r.diarization_parallel),
        ) for r in rows],
        total=count, page=page, page_size=page_size,
        pages=max(1, math.ceil(count / page_size)),
        summary=ProcessingSummary(
            count=count, audio_sec=int(audio_total), processing_sec=int(processing_total),
            ratio=_ratio(processing_total, audio_total),
        ),
    )


# ── Coada de transcriere ─────────────────────────────────────

class QueueItem(BaseModel):
    recording_id: str
    title: Optional[str]                 # None = înregistrarea a fost ștearsă
    duration_seconds: Optional[int]
    status: Optional[str]
    created_at: Optional[datetime]
    jobs: int = 1                        # sesiune multi-fișier: mai multe joburi


class RunningItem(QueueItem):
    worker_id: str
    worker_alive: bool                   # False = worker-ul nu mai publică starea (oprit / repornește)
    progress: Dict[str, int]             # {"transcriere": 100, "aliniere": 40, ...}
    cancelling: bool                     # worker-ul oprește jobul
    cancel_requested: bool               # anulare cerută, încă neobservată de worker


class QueueResponse(BaseModel):
    available: bool                      # False = Redis indisponibil
    running: List[RunningItem]
    waiting: List[QueueItem]


class QueueActionResponse(BaseModel):
    removed: int                         # joburi scoase din coadă
    running: bool                        # era în transcriere → oprirea a fost cerută


def _uuid_or_none(value: str) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


async def _recordings_by_id(db: AsyncSession, ids: List[str]) -> Dict[str, Any]:
    valid = [u for u in (_uuid_or_none(i) for i in ids) if u is not None]
    if not valid:
        return {}
    rows = (await db.execute(
        select(Recording.id, Recording.title, Recording.duration_seconds,
               Recording.status, Recording.created_at)
        .where(Recording.id.in_(valid))
    )).all()
    return {str(r.id): r for r in rows}


def _recording_fields(recording) -> Dict[str, Any]:
    if recording is None:
        return {"title": None, "duration_seconds": None, "status": None, "created_at": None}
    status = recording.status
    return {
        "title": recording.title,
        "duration_seconds": recording.duration_seconds,
        "status": str(status.value if hasattr(status, "value") else status),
        "created_at": recording.created_at,
    }


@router.get("/queue", response_model=QueueResponse, summary="Coada de transcriere")
async def get_queue(
    _: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    queue: QueueService = Depends(get_queue_service),
):
    try:
        running = await queue.running()
        waiting = await queue.waiting()
    except Exception as e:
        logger.warning("admin_queue_redis_error", error=str(e))
        return QueueResponse(available=False, running=[], waiting=[])

    recordings = await _recordings_by_id(
        db, [i["recording_id"] for i in running] + [i["recording_id"] for i in waiting])
    return QueueResponse(
        available=True,
        running=[RunningItem(**item, **_recording_fields(recordings.get(item["recording_id"])))
                 for item in running],
        waiting=[QueueItem(**item, **_recording_fields(recordings.get(item["recording_id"])))
                 for item in waiting],
    )


@router.post("/queue/{recording_id}/cancel", response_model=QueueActionResponse,
             summary="Anulează transcrierea (în așteptare sau în curs)")
async def cancel_transcription(
    recording_id: uuid.UUID,
    request: Request,
    _: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    queue: QueueService = Depends(get_queue_service),
):
    """
    Scoate înregistrarea din coadă; dacă e în transcriere, worker-ul o oprește
    în câteva secunde (la sfârșitul lotului curent), fără repornire.
    Înregistrarea rămâne, cu status 'cancelled', și poate fi repornită cu „Reîncearcă”.
    """
    recording = await db.scalar(select(Recording).where(Recording.id == recording_id))
    active = recording is not None and recording.status in (
        RecordingStatus.QUEUED.value, RecordingStatus.TRANSCRIBING.value)
    try:
        result = await queue.cancel(str(recording_id))
    except Exception as e:
        logger.warning("admin_queue_cancel_redis_error", recording_id=str(recording_id), error=str(e))
        raise HTTPException(status_code=503, detail="Coada de transcriere nu este disponibilă.")

    if not (active or result["removed"] or result["running"]):
        raise HTTPException(status_code=409, detail="Înregistrarea nu este în coada de transcriere.")

    if active:
        recording.status = RecordingStatus.CANCELLED.value
        recording.error_message = None
        transcript = await db.scalar(select(Transcript).where(Transcript.recording_id == recording_id))
        if transcript is not None and transcript.status != TranscriptStatus.COMPLETED.value:
            transcript.status = TranscriptStatus.CANCELLED.value
            transcript.error_message = None

    await log_audit(request, db, action="TRANSCRIBE", resource_type="recording", resource_id=recording_id,
                    details={"resource_name": recording.title if recording else None, "event": "cancel"})
    await db.commit()
    logger.info("transcription_cancelled", recording_id=str(recording_id), **result)
    return QueueActionResponse(**result)


@router.post("/queue/{recording_id}/prioritize", summary="Mută înregistrarea prima în coadă")
async def prioritize_transcription(
    recording_id: uuid.UUID,
    request: Request,
    _: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    queue: QueueService = Depends(get_queue_service),
):
    try:
        moved = await queue.move_to_front(str(recording_id))
    except Exception as e:
        logger.warning("admin_queue_prioritize_redis_error", recording_id=str(recording_id), error=str(e))
        raise HTTPException(status_code=503, detail="Coada de transcriere nu este disponibilă.")
    if not moved:
        raise HTTPException(status_code=409, detail="Înregistrarea nu mai așteaptă în coadă.")

    title = await db.scalar(select(Recording.title).where(Recording.id == recording_id))
    await log_audit(request, db, action="TRANSCRIBE", resource_type="recording", resource_id=recording_id,
                    details={"resource_name": title, "event": "prioritize"})
    await db.commit()
    return {"moved": True}
