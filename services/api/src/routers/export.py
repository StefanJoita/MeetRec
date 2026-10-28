# services/api/src/routers/export.py
# ============================================================
# Export Router — PDF / DOCX / TXT
# ============================================================

import io
import re
from xml.sax.saxutils import escape   # reportlab interpretează marcaje în Paragraph
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.limiter import limiter
from src.middleware.audit import log_audit
from src.middleware.auth import get_current_user, check_recording_access
from src.models.audit_log import User
from src.models.recording import Recording
from src.services.classification import classification_label
from src.services.export_naming import attachment_headers, export_filename
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


def _default_speaker_label(speaker_id: str) -> str:
    """„SPEAKER_00” → „Vorbitor 1” (aceeași etichetă ca în interfață); altceva → necunoscut."""
    match = re.fullmatch(r"SPEAKER_(\d+)", speaker_id)
    return f"Vorbitor {int(match.group(1)) + 1}" if match else "Vorbitor necunoscut"


def _paragraphs(segments, display_map: dict) -> list[tuple[float, str | None, str]]:
    """
    (început, vorbitor, text): segmentele consecutive ale aceluiași vorbitor devin
    un singur paragraf, ca într-un proces-verbal. Fără vorbitor, fiecare segment
    rămâne separat.
    """
    paragraphs: list[list] = []
    previous = None
    for seg in segments:
        speaker = seg.speaker_id or None
        if speaker is not None and speaker == previous and paragraphs:
            paragraphs[-1][2].append(seg.text)
        else:
            label = display_map.get(speaker) if speaker else None
            paragraphs.append([float(seg.start_time), label, [seg.text]])
        previous = speaker
    return [(start, label, " ".join(t.strip() for t in texts)) for start, label, texts in paragraphs]


async def _build_speaker_display_map(
    segments, speaker_mapping: dict, db: AsyncSession
) -> dict[str, str]:
    """
    Construiește un dict {speaker_id → nume afișabil} pentru toate segmentele.

    Rezolvă două cazuri:
      1. speaker_id este deja un UUID de user (post-rezolvare directă)
      2. speaker_id este "SPEAKER_XX" → speaker_mapping["SPEAKER_XX"] = user_uuid → nume user
    Vorbitorii neasociați (sau asociați cu un user șters) apar ca „Vorbitor N”.
    """
    speaker_ids = {seg.speaker_id for seg in segments if seg.speaker_id}
    if not speaker_ids:
        return {}

    display_map: dict[str, str] = {}
    # speaker_id (cheie în segmente) → UUID de user de rezolvat
    to_resolve: dict[str, uuid.UUID] = {}

    for sid in speaker_ids:
        try:
            # Cazul 1: speaker_id este direct un UUID de user
            to_resolve[sid] = uuid.UUID(sid)
        except ValueError:
            # Cazul 2: "SPEAKER_XX" — căutăm în speaker_mapping
            raw = speaker_mapping.get(sid)
            if raw:
                try:
                    to_resolve[sid] = uuid.UUID(raw)
                except ValueError:
                    display_map[sid] = raw  # valoare neparsabilă, o afișăm direct

    if to_resolve:
        unique_uuids = list({str(u) for u in to_resolve.values()})
        result = await db.execute(
            select(User).where(User.id.in_([uuid.UUID(u) for u in unique_uuids]))
        )
        user_names = {str(u.id): (u.full_name or u.username) for u in result.scalars().all()}
        for sid, uid in to_resolve.items():
            name = user_names.get(str(uid))
            if name:
                display_map[sid] = name

    for sid in speaker_ids - display_map.keys():
        display_map[sid] = _default_speaker_label(sid)

    return display_map


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
@limiter.limit("20/hour")
async def export_transcript(
    request: Request,
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

    if not await check_recording_access(recording_id, current_user, db):
        raise HTTPException(status_code=403, detail="Acces interzis la această înregistrare.")

    await log_audit(
        request, db,
        action="EXPORT",
        resource_type="recording",
        resource_id=recording_id,
        details={"resource_name": recording.title, "format": format,
                 "classification": recording.classification},
    )

    # Nivelul înregistrării: codul în numele fișierului, denumirea în antetul documentului
    filename = export_filename(recording.title, format, recording.classification)
    level = classification_label(recording.classification)
    display_map = await _build_speaker_display_map(
        transcript.segments, recording.speaker_mapping or {}, db
    )

    if format == "txt":
        return _export_txt(recording, transcript, filename, level, display_map)
    elif format == "pdf":
        return _export_pdf(recording, transcript, filename, level, display_map)
    elif format == "docx":
        return _export_docx(recording, transcript, filename, level, display_map)


# ── TXT ──────────────────────────────────────────────────────

def _export_txt(recording, transcript, filename: str, level: str, display_map: dict) -> StreamingResponse:
    lines = [
        level.center(60).rstrip(),
        "",
        f"TRANSCRIERE: {recording.title}",
        f"Data ședinței: {recording.meeting_date}",
        f"Durată: {recording.duration_formatted}",
        f"Limbă: {transcript.language or 'necunoscută'}",
        f"Exportat: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        "",
        "=" * 60,
        "",
    ]
    for start, label, text in _paragraphs(transcript.segments, display_map):
        timestamp = f"[{_format_time(start)}]"
        if label:
            lines.append(f"{timestamp} {label}: {text}")
            lines.append("")                       # rând liber între intervenții
        else:
            lines.append(f"{timestamp}  {text}")

    content = "\n".join(lines)
    buf = io.BytesIO(content.encode("utf-8"))

    return StreamingResponse(
        buf,
        media_type="text/plain; charset=utf-8",
        headers=attachment_headers(filename),
    )


# ── PDF ──────────────────────────────────────────────────────

def _register_pdf_fonts() -> tuple[str, str]:
    """
    Înregistrează fonturile DejaVu (suport Unicode complet, inclusiv diacritice românești).
    Returnează (font_normal, font_bold).
    Fallback la Helvetica dacă fonturile nu sunt disponibile în container.
    """
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    font_path_normal = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    font_path_bold = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

    import os
    if os.path.exists(font_path_normal) and os.path.exists(font_path_bold):
        pdfmetrics.registerFont(TTFont("DejaVuSans", font_path_normal))
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", font_path_bold))
        return "DejaVuSans", "DejaVuSans-Bold"
    return "Helvetica", "Helvetica-Bold"


def _export_pdf(recording, transcript, filename: str, level: str, display_map: dict) -> StreamingResponse:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    font_normal, font_bold = _register_pdf_fonts()

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
        fontName=font_bold,
    )
    meta_style = ParagraphStyle(
        "Meta",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.gray,
        spaceAfter=2,
        fontName=font_normal,
    )
    segment_style = ParagraphStyle(
        "Segment",
        parent=styles["Normal"],
        fontSize=10,
        spaceAfter=4,
        leading=14,
        fontName=font_normal,
    )
    timestamp_style = ParagraphStyle(
        "Timestamp",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.HexColor("#666666"),
        spaceAfter=1,
        fontName=font_normal,
    )
    speaker_style = ParagraphStyle(
        "Speaker",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.HexColor("#1a56a0"),
        spaceAfter=1,
        fontName=font_bold,
    )

    story = []

    # Titlu
    story.append(Paragraph(escape(recording.title), title_style))
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
    for start, label, text in _paragraphs(transcript.segments, display_map):
        ts = _format_time(start)
        if label:
            story.append(Paragraph(f"{ts} · {escape(label)}", speaker_style))
        else:
            story.append(Paragraph(ts, timestamp_style))
        story.append(Paragraph(escape(text), segment_style))

    def classification_header(canvas, _doc):
        # Nivelul de secretizare în antetul fiecărei pagini
        canvas.saveState()
        canvas.setFont(font_bold, 9)
        canvas.drawCentredString(A4[0] / 2, A4[1] - 1.5 * cm, level)
        canvas.restoreState()

    doc.build(story, onFirstPage=classification_header, onLaterPages=classification_header)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers=attachment_headers(filename),
    )


# ── DOCX ─────────────────────────────────────────────────────

def _export_docx(recording, transcript, filename: str, level: str, display_map: dict) -> StreamingResponse:
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
        # Nivelul de secretizare în antetul fiecărei pagini
        header = section.header.paragraphs[0]
        header.alignment = WD_ALIGN_PARAGRAPH.CENTER
        header_run = header.add_run(level)
        header_run.bold = True
        header_run.font.size = Pt(9)

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
    for start, label, text in _paragraphs(transcript.segments, display_map):
        ts = _format_time(start)

        ts_par = doc.add_paragraph()
        if label:
            ts_run = ts_par.add_run(f"[{ts}] {label}")
            ts_run.font.color.rgb = RGBColor(0x1A, 0x56, 0xA0)
        else:
            ts_run = ts_par.add_run(f"[{ts}]")
            ts_run.font.color.rgb = RGBColor(0x88, 0x88, 0x88)
        ts_run.font.size = Pt(8)
        ts_run.bold = True

        text_par = doc.add_paragraph(text)
        text_par.style.font.size = Pt(10)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=attachment_headers(filename),
    )
