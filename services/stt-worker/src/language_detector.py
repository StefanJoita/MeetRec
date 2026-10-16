# services/stt-worker/src/language_detector.py
# ============================================================
# Language Detector — detectează limba din primele 30s de vorbire
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

from src.config import settings

logger = structlog.get_logger(__name__)

# Sub acest RMS (audio float în [-1, 1]) o fereastră e considerată liniște (~ -46 dBFS)
_SILENCE_RMS = 0.005
# Probabilitatea minimă ca o altă limbă decât cea principală să o înlocuiască
_MIN_OVERRIDE_PROBABILITY = 0.5


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
            Dacă detectarea eșuează, returnează limba principală (WHISPER_PRIMARY_LANGUAGE).
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
                fallback=settings.whisper_primary_language,
            )
            return settings.whisper_primary_language

    def _detect_sync(self, file_path: str) -> str:
        """
        Detectare sincronă — rulată în thread pool.

        Pași:
        1. Încarcă fișierul audio (float32, 16 kHz mono) și sare peste liniștea
           de la început — multe ședințe încep cu câteva zeci de secunde de tăcere,
           pe care Whisper le „recunoaște" de obicei ca engleză
        2. Calculează spectrograma mel pentru primele 30 s de după liniște
        3. Encoderul Whisper + detect_language → probabilitatea fiecărei limbi
        4. Alege limba cea mai probabilă dintre WHISPER_DETECT_LANGUAGES

        NU folosim pipeline.transcribe() / pipeline.detect_language() din WhisperX:
        modelul e încărcat cu language="ro", așa că transcribe() nu detectează nimic
        (folosește limba fixată), iar detect_language() întoarce doar limba, fără
        probabilitate. Apelăm aceiași pași ca whisperx 3.8.6 (asr.py, detect_language)
        — la upgrade, verifică că atributele de mai jos există încă.
        """
        import whisperx
        from whisperx.audio import N_SAMPLES, log_mel_spectrogram

        audio = whisperx.load_audio(file_path)
        audio = audio[_speech_start(audio):][:N_SAMPLES]

        whisper_model = self._model.model                     # faster_whisper.WhisperModel
        n_mels = whisper_model.feat_kwargs.get("feature_size") or 80
        mel = log_mel_spectrogram(audio, n_mels=n_mels, padding=N_SAMPLES - audio.shape[0])
        encoder_output = whisper_model.encode(mel)
        results = whisper_model.model.detect_language(encoder_output)[0]
        probabilities = {token[2:-2]: prob for token, prob in results}   # "<|en|>" → "en"

        return choose_language(probabilities)


def _speech_start(audio, sample_rate: int = 16000) -> int:
    """
    Indexul primei ferestre de 0,5 s cu sunet peste pragul de liniște.
    Fără niciun sunet → 0 (detectăm pe începutul fișierului, ca înainte).
    """
    import numpy as np

    window = sample_rate // 2
    frames = len(audio) // window
    if frames == 0:
        return 0
    rms = np.sqrt(np.mean(audio[: frames * window].reshape(frames, window) ** 2, axis=1))
    loud = np.flatnonzero(rms > _SILENCE_RMS)
    return int(loud[0]) * window if loud.size else 0


def choose_language(probabilities: dict) -> str:
    """
    Limba cea mai probabilă dintre cele acceptate (WHISPER_DETECT_LANGUAGES).

    Altă limbă decât cea principală trebuie să fie clar dominantă
    (≥ _MIN_OVERRIDE_PROBABILITY): la vorbire neclară sau zgomot, Whisper
    împrăștie probabilitățile, iar o ședință în română nu trebuie transcrisă
    ca engleză din cauza unei detecții la limită.
    """
    primary = settings.whisper_primary_language
    allowed = [lang.strip() for lang in settings.whisper_detect_languages.split(",") if lang.strip()]
    if primary not in allowed:
        allowed.insert(0, primary)

    best = max(allowed, key=lambda lang: probabilities.get(lang, 0.0))
    if best != primary and probabilities.get(best, 0.0) < _MIN_OVERRIDE_PROBABILITY:
        logger.info("language_detection_uncertain", best=best,
                    probability=round(probabilities.get(best, 0.0), 2), fallback=primary)
        return primary
    return best
