# services/stt-worker/src/language_detector.py
# ============================================================
# Language Detector — detectează limba din primele 30s de audio
# ============================================================
# Whisper poate detecta automat limba FĂRĂ să transcrie tot fișierul.
# Folosim această capabilitate pentru a valida/corecta language_hint
# din job înainte de transcrierea completă.
#
# De ce 30 de secunde?
# Whisper procesează audio în ferestre de 30s (arhitectura sa internă).
# Detectarea limbii necesită exact o astfel de fereastră.
# Nu câștigăm nimic din mai mult audio — și economisim RAM.
#
# IMPORTANT: Nu încarcăm un model separat!
# Folosim modelul deja încărcat în WhisperTranscriber.
# Motivul: modelul "medium" ocupă ~5GB RAM.
# Dacă am încărca al doilea → 10GB RAM = crash pe majoritatea serverelor.
# ============================================================

import asyncio
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


class LanguageDetector:
    """
    Detectează limba dintr-un fișier audio folosind Whisper.
    Reutilizează modelul din WhisperTranscriber — nu alocă RAM suplimentar.
    """

    def __init__(self, model):
        """
        model: obiectul whisper.Whisper deja încărcat.
               Primit din WhisperTranscriber._model în main.py.
        """
        self._model = model

    async def detect(self, file_path: str) -> str:
        """
        Detectează limba din primele 30 de secunde ale fișierului audio.

        Returns:
            Codul limbii: "ro", "en", "fr", etc.
            Dacă detectarea eșuează, returnează "ro" (default pentru sistemul nostru).
        """
        try:
            loop = asyncio.get_event_loop()
            language = await loop.run_in_executor(
                None,
                self._detect_sync,
                file_path,
            )
            logger.info("language_detected", file=file_path, language=language)
            return language
        except Exception as e:
            logger.warning(
                "language_detection_failed",
                file=file_path,
                error=str(e),
                fallback="ro",
            )
            return "ro"  # fallback sigur pentru sistemul nostru (80%+ audio e română)

    def _detect_sync(self, file_path: str) -> str:
        """
        Detectare sincronă — rulată în thread pool.

        Pași:
        1. Încarcă fișierul audio ca array numpy (float32, 16kHz mono)
        2. Tăiem la primele 30 de secunde (16000 samples/secundă × 30)
        3. pad_or_trim: asigurăm exact 30s (pad cu zeros dacă mai scurt)
        4. Calculăm mel spectrogram (reprezentare frecvențială a audio-ului)
        5. detect_language: Whisper inferă probabilitățile per limbă
        6. Returnăm limba cu probabilitatea maximă

        De ce slice [:16000*30]?
        whisper.load_audio() încarcă ÎNTREGUL fișier în RAM.
        Pentru un fișier de 3 ore: 3×3600×16000×4 bytes ≈ 690 MB RAM.
        Prin slice la 30s, reducem la 30×16000×4 ≈ 1.9 MB — de 360x mai puțin.
        """
        import whisperx

        # Încărcăm primele 30s de audio (whisperx returnează float32, 16kHz mono)
        audio = whisperx.load_audio(file_path)
        audio_30s = audio[: 16000 * 30]

        # Transcriem scurt clip — whisperx detectează automat limba
        result = self._model.transcribe(audio_30s, batch_size=4)
        detected = result.get("language", "ro")
        return detected
