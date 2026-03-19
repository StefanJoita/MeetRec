# services/api/src/routers/export.py
# ============================================================
# Export Router — PDF / DOCX / TXT
# ============================================================

import io
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.middleware.auth import get_current_user
from src.models.audit_log import User
from src.models.recording import Recording
from src.services.transcript_service import TranscriptService
from sqlalchemy import select

router = APIRouter(prefix="/export", tags=["export"])


def _format_time(seconds: float) -> str:
    """Convertește secunde în format MM:SS."""
    total = int(seconds)
    m, s = divmod(total, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


async def _get_transcript_and_recording(
    recording_id: uuid.UUID,
    db: AsyncSession,
):
    """Obține transcriptul și înregistrarea. Ridică 404 dacă nu există."""
    rec_result = await db.execute(
        select(Recording).where(Recording.id == recording_id)
    )
    recording = rec_result.scalar_one_or_none()
    if not recording:
        raise HTTPException(status_code=404, detail="Înregistrarea nu există.")

    service = TranscriptService(db)
    transcript = await service.get_by_recording_id(recording_id)
    if not transcript or transcript.status != "completed":
        raise HTTPException(
            status_code=404,
            detail="Transcriptul nu este disponibil sau nu a fost finalizat.",
        )
    return recording, transcript


@router.get(
    "/recording/{recording_id}",
    summary="Exportă transcriptul (PDF / DOCX / TXT)",
)
async def export_transcript(
    recording_id: uuid.UUID,
    format: str = Query(default="txt", pattern="^(pdf|docx|txt)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Exportă transcriptul unei înregistrări în formatul dorit.

    - **pdf** — document PDF formatat, cu titlu și timestamps
    - **docx** — document Word cu stiluri
    - **txt** — text simplu, ușor de prelucrat
    """
    recording, transcript = await _get_transcript_and_recording(recording_id, db)

    filename_base = recording.title.replace(" ", "_")[:50]

    if format == "txt":
        return _export_txt(recording, transcript, filename_base)
    elif format == "pdf":
        return _export_pdf(recording, transcript, filename_base)
    elif format == "docx":
        return _export_docx(recording, transcript, filename_base)


# ── TXT ──────────────────────────────────────────────────────

def _export_txt(recording, transcript, filename_base: str) -> StreamingResponse:
    lines = [
        f"TRANSCRIERE: {recording.title}",
        f"Data ședinței: {recording.meeting_date}",
        f"Durată: {recording.duration_formatted}",
        f"Limbă: {transcript.language or 'necunoscută'}",
        f"Exportat: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        "",
        "=" * 60,
        "",
    ]
    for seg in transcript.segments:
        timestamp = f"[{_format_time(float(seg.start_time))}]"
        lines.append(f"{timestamp}  {seg.text}")

    content = "\n".join(lines)
    buf = io.BytesIO(content.encode("utf-8"))

    return StreamingResponse(
        buf,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename_base}.txt"'},
    )


# ── PDF ──────────────────────────────────────────────────────

def _export_pdf(recording, transcript, filename_base: str) -> StreamingResponse:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2.5 * cm,
        rightMargin=2.5 * cm,
        topMargin=2.5 * cm,
        bottomMargin=2.5 * cm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Title"],
        fontSize=16,
        spaceAfter=6,
    )
    meta_style = ParagraphStyle(
        "Meta",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.gray,
        spaceAfter=2,
    )
    segment_style = ParagraphStyle(
        "Segment",
        parent=styles["Normal"],
        fontSize=10,
        spaceAfter=4,
        leading=14,
    )
    timestamp_style = ParagraphStyle(
        "Timestamp",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.HexColor("#666666"),
        spaceAfter=1,
    )

    story = []

    # Titlu
    story.append(Paragraph(recording.title, title_style))
    story.append(Paragraph(f"Data ședinței: {recording.meeting_date}", meta_style))
    story.append(Paragraph(f"Durată: {recording.duration_formatted}", meta_style))
    story.append(Paragraph(
        f"Limbă: {transcript.language or 'necunoscută'} · "
        f"Cuvinte: {transcript.word_count} · "
        f"Exportat: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        meta_style,
    ))
    story.append(Spacer(1, 0.5 * cm))

    # Linie separatoare
    story.append(Table(
        [[""]],
        colWidths=["100%"],
        style=TableStyle([
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.lightgrey),
        ]),
    ))
    story.append(Spacer(1, 0.4 * cm))

    # Segmente
    for seg in transcript.segments:
        ts = _format_time(float(seg.start_time))
        story.append(Paragraph(ts, timestamp_style))
        story.append(Paragraph(seg.text, segment_style))

    doc.build(story)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename_base}.pdf"'},
    )


# ── DOCX ─────────────────────────────────────────────────────

def _export_docx(recording, transcript, filename_base: str) -> StreamingResponse:
    from docx import Document
    from docx.shared import Pt, RGBColor, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document()

    # Margini
    for section in doc.sections:
        section.top_margin = Cm(2.5)
        section.bottom_margin = Cm(2.5)
        section.left_margin = Cm(2.5)
        section.right_margin = Cm(2.5)

    # Titlu
    title_par = doc.add_heading(recording.title, level=1)
    title_par.alignment = WD_ALIGN_PARAGRAPH.LEFT

    # Metadata
    meta = doc.add_paragraph()
    meta.add_run(f"Data ședinței: {recording.meeting_date}\n").font.size = Pt(9)
    meta.add_run(f"Durată: {recording.duration_formatted}\n").font.size = Pt(9)
    run = meta.add_run(
        f"Limbă: {transcript.language or 'necunoscută'} · "
        f"Cuvinte: {transcript.word_count} · "
        f"Exportat: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0x80, 0x80, 0x80)

    doc.add_paragraph()  # spațiu

    # Segmente
    for seg in transcript.segments:
        ts_par = doc.add_paragraph()
        ts_run = ts_par.add_run(f"[{_format_time(float(seg.start_time))}]")
        ts_run.font.size = Pt(8)
        ts_run.font.color.rgb = RGBColor(0x88, 0x88, 0x88)
        ts_run.bold = True

        text_par = doc.add_paragraph(seg.text)
        text_par.style.font.size = Pt(10)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename_base}.docx"'},
    )
