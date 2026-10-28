# services/api/src/services/export_naming.py
# ============================================================
# Numele fișierelor exportate: AAAALLZZ_NIVEL_Denumire_document.ext
# ============================================================
# AAAALLZZ = data exportului; NIVEL = codul nivelului de clasificare al
# înregistrării (N, SSv, S, SS). Exporturile care nu țin de o înregistrare
# (jurnalul de audit) nu au nivel: AAAALLZZ_Denumire_document.ext.
# ============================================================

import re
from datetime import date
from typing import Dict, Optional
from urllib.parse import quote

MAX_NAME_LENGTH = 80


def document_name(title: str) -> str:
    """
    Titlul ca parte din numele fișierului: fără caractere interzise în Windows
    sau în header-ul Content-Disposition (CR/LF, ghilimele), spațiile → „_”.
    """
    safe = re.sub(r'[\x00-\x1f\x7f<>:"/\\|?*]', '', title)
    safe = re.sub(r'[\s_]+', '_', safe.strip()).strip('._')
    return safe[:MAX_NAME_LENGTH].rstrip('._') or 'Document'


def export_filename(title: str, ext: str, classification: Optional[str] = None,
                    on: Optional[date] = None) -> str:
    parts = [(on or date.today()).strftime('%Y%m%d')]
    if classification:
        parts.append(classification)
    parts.append(document_name(title))
    return f"{'_'.join(parts)}.{ext}"


def attachment_headers(filename: str) -> Dict[str, str]:
    """Content-Disposition cu numele în UTF-8 (diacriticele se păstrează)."""
    return {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
