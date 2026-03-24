# services/stt-worker/src/audio_assembler.py
# ============================================================
# Audio Assembler — concatenează segmentele unei sesiuni
# ============================================================
# Primește lista de căi audio (în ordinea segment_index),
# le concatenează cu pydub și returnează un fișier WAV temporar
# gata de transcris cu Whisper.
#
# De ce concatenăm ÎNAINTE de Whisper, nu după?
#   Dacă transcriem per-segment, Whisper nu are context la joncțiuni:
#   cuvintele de la finalul unui segment și începutul celui următor
#   pot fi trunchiate sau greșit transcrise (lipsă context acustic).
#   Pe audio concatenat, Whisper vede întreaga frază.
#
# De ce WAV la ieșire?
#   WAV (PCM) nu necesită decodare la intrarea în Whisper.
#   MP3/OGG/etc. adaugă overhead de decodare în Whisper.
#   Diferența e mică, dar WAV e mai predictibil.
#
# De ce pydub și nu ffmpeg subprocess?
#   pydub oferă o interfață Python curată pentru concatenare.
#   ffmpeg subprocess ar fi mai rapid pentru fișiere mari,
#   dar adaugă complexitate de gestionare a proceselor.
#   pydub folosește oricum ffmpeg intern.
# ============================================================

import asyncio
import tempfile
from pathlib import Path
from typing import List

import structlog
from pydub import AudioSegment

logger = structlog.get_logger(__name__)


class AssemblyError(Exception):
    """Eroare la asamblarea segmentelor audio."""


class AudioAssembler:
    """
    Concatenează o listă de fișiere audio în ordinea dată
    și exportă rezultatul ca fișier WAV temporar.
    """

    async def assemble(self, paths: List[Path]) -> Path:
        """
        Concatenează fișierele audio în ordinea listei.

        Args:
            paths: Căile fișierelor audio, deja sortate după segment_index.

        Returns:
            Calea fișierului WAV temporar concatenat.
            IMPORTANT: Caller-ul este responsabil de ștergerea fișierului după transcriere.

        Raises:
            AssemblyError: dacă un fișier lipsește sau concatenarea eșuează.
        """
        if not paths:
            raise AssemblyError("Nu există segmente audio de asamblat.")

        # Verificăm că toate fișierele există ÎNAINTE de a începe concatenarea
        for path in paths:
            if not path.exists():
                raise AssemblyError(
                    f"Fișier audio lipsă: {path}. "
                    "Segmentul poate fi încă în curs de upload sau a fost șters."
                )

        logger.info(
            "assembly_started",
            segments=len(paths),
            files=[p.name for p in paths],
        )

        # Concatenarea pydub este sincronă și poate dura 10-30s pentru 1h audio
        # → o rulăm în executor ca să nu blocăm event loop-ul
        loop = asyncio.get_running_loop()
        try:
            merged_path = await loop.run_in_executor(
                None,
                self._concatenate_sync,
                paths,
            )
        except Exception as e:
            raise AssemblyError(f"Concatenare eșuată: {e}") from e

        logger.info(
            "assembly_done",
            merged_file=merged_path.name,
            size_mb=round(merged_path.stat().st_size / 1024 / 1024, 1),
        )
        return merged_path

    def _concatenate_sync(self, paths: List[Path]) -> Path:
        """
        Concatenare sincronă cu pydub. Rulată în thread pool de assemble().
        """
        combined = AudioSegment.empty()
        for path in paths:
            segment = AudioSegment.from_file(str(path))
            combined += segment

        # Fișier temporar cu sufix .wav — va fi șters de consumer după transcriere
        tmp = tempfile.NamedTemporaryFile(
            suffix=".wav",
            delete=False,
            prefix="meetrec_session_",
        )
        tmp.close()
        tmp_path = Path(tmp.name)

        combined.export(str(tmp_path), format="wav")
        return tmp_path
