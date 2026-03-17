# services/stt-worker/src/postprocessor.py
# ============================================================
# Post-Processor — curăță textul raw de la Whisper
# ============================================================
# Pure Python: fără dependențe externe, fără DB, fără Redis.
# Cea mai ușor de testat componentă din întreg proiectul:
#   pp = PostProcessor()
#   result = pp.process(segments)
#   assert result[0].text == "text corect"
# Nu ai nevoie de mock-uri sau DB pentru aceste teste.
#
# Probleme rezolvate:
#   1. Diacritice românești incorecte (cedilla vs comma-below)
#   2. Spații multiple / spații la margini
#
# NOTĂ despre diacritice — povestea completă:
#   Română are ș, ț, ă, â, î (cu comma-below sau literă specială).
#   Ș (U+0218) și ș (U+0219) sunt CORECTE (comma-below, standard din 2003).
#   Ş (U+015E) și ş (U+015F) sunt VECHI (cedilla, din encodări legacy).
#   Dacă salvăm varianta cu cedilla în DB, căutarea full-text în PostgreSQL
#   cu config 'romanian' poate rata match-uri:
#     plainto_tsquery('romanian', 'ședin') NU se potrivește cu 'şedin'
# ============================================================

import re
from copy import replace
from typing import List

from src.transcriber import TranscriptSegment


class PostProcessor:
    """
    Procesează lista de segmente transcript după transcriere Whisper.
    Operații: normalizare diacritice + normalizare spații.
    """

    # Mapare completă cedilla → comma-below pentru română
    # Cheie = caracterul vechi (cedilla), Valoare = caracterul corect (comma-below)
    _DIACRITICS_MAP = {
        "\u015f": "\u0219",  # ş → ș (s cu cedilla → s cu comma-below)
        "\u015e": "\u0218",  # Ş → Ș (S cu cedilla → S cu comma-below)
        "\u0163": "\u021b",  # ţ → ț (t cu cedilla → t cu comma-below)
        "\u0162": "\u021a",  # Ţ → Ț (T cu cedilla → T cu comma-below)
    }

    def process(self, segments: List[TranscriptSegment]) -> List[TranscriptSegment]:
        """
        Aplică toate transformările pe o listă de segmente.

        Returnează o NOUĂ listă cu segmente noi (nu modificăm input-ul).
        Pattern: immutabilitate — mai sigur, mai predictibil în teste.
        """
        return [self._fix_segment(seg) for seg in segments]

    def _fix_segment(self, seg: TranscriptSegment) -> TranscriptSegment:
        """Aplică toate transformările pe un singur segment."""
        text = seg.text
        text = self._fix_diacritics(text)
        text = self._normalize_whitespace(text)

        # Creăm un segment nou cu textul corectat
        # Celelalte câmpuri (start_time, end_time, confidence, etc.) rămân neschimbate
        return TranscriptSegment(
            segment_index=seg.segment_index,
            start_time=seg.start_time,
            end_time=seg.end_time,
            text=text,
            confidence=seg.confidence,
            language=seg.language,
        )

    def _fix_diacritics(self, text: str) -> str:
        """
        Înlocuiește variantele cu cedilla cu variantele corecte (comma-below).

        Folosim str.replace() simplu — ușor de citit și de verificat.
        Nu folosim str.translate() cu tabele Unicode (mai rapid dar mai criptic).
        Pentru un număr mic de caractere (4 perechi), diferența de perf e neglijabilă.
        """
        for wrong, correct in self._DIACRITICS_MAP.items():
            text = text.replace(wrong, correct)
        return text

    def _normalize_whitespace(self, text: str) -> str:
        """
        Elimină spații multiple și spații la margini.

        Whisper produce uneori:
          - Spațiu la început: " Bună ziua." → "Bună ziua."
          - Spații duble după punctuație: "da.  Și eu." → "da. Și eu."
          - Tab-uri sau newline-uri: rare dar posibile cu audio de calitate slabă

        re.sub(r'\\s+', ' ', text):
            \\s+ = orice secvență de 1+ whitespace (spație, tab, newline)
            ' '  = înlocuită cu un singur spațiu
        .strip() = elimină spațiile de la început și sfârșit
        """
        text = re.sub(r"\s+", " ", text)
        return text.strip()
