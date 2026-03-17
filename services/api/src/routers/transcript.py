# services/api/src/routers/transcripts.py
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from src.schemas.recording import TranscriptResponse
from src.services.transcript_service import TranscriptService
from src.middleware.audit import log_audit

router = APIRouter(prefix="/transcripts", tags=["transcripts"])


def get_service(db: AsyncSession = Depends(get_db)) -> TranscriptService:
    return TranscriptService(db)


@router.get(
    "/recording/{recording_id}",
    response_model=TranscriptResponse,
    summary="Obține transcriptul unei înregistrări",
)
async def get_transcript(
    recording_id: uuid.UUID,
    request: Request,
    service: TranscriptService = Depends(get_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Returnează transcriptul complet cu toate segmentele și timestamp-urile.
    Segmentele sunt ordonate cronologic (segment_index ASC).
    """
    transcript = await service.get_by_recording_id(recording_id)
    if not transcript:
        raise HTTPException(status_code=404, detail="Transcriptul nu există sau nu e gata.")

    await log_audit(request, db, action="VIEW", resource_type="transcript",
                    resource_id=transcript.id)
    return transcript


@router.post(
    "/recording/{recording_id}/retry",
    summary="Retrimite la transcriere",
)
async def retry_transcription(
    recording_id: uuid.UUID,
    request: Request,
    service: TranscriptService = Depends(get_service),
):
    """
    Retrimierea unui job de transcriere eșuat.
    Util când STT Worker a căzut sau modelul a dat eroare.
    """
    result = await service.retry(recording_id)
    if not result:
        raise HTTPException(
            status_code=400,
            detail="Nu se poate retrimi. Verificați că înregistrarea există și are status 'failed'."
        )
    return {"message": "Job retrimat cu succes.", "recording_id": str(recording_id)}