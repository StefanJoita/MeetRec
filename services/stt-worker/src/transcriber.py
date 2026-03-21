# services/stt-worker/src/transcriber.py
# ============================================================
# Whisper Transcriber — convertește audio în text cu timestamps
# ============================================================
# Whisper este o bibliotecă SINCRONĂ care blochează thread-ul
# curent pe toată durata transcrierii (10+ minute pentru fișiere mari).
#
# Problemă: dacă o apelăm direct din async def, blocăm
# întregul event loop asyncio — nicio altă operație async
# nu mai poate rula!
#
# Soluție: asyncio.run_in_executor(None, func)
#   → rulează func() într-un thread din pool-ul OS
#   → event loop-ul asyncio rămâne liber
#   → returnează un Future pe care îl putem await
#
# Analogie:
#   "Dă sarcina asta unui muncitor separat și spune-mi când termină.
#   Eu (event loop) continui cu alte lucruri între timp."
# ============================================================

import asyncio
import math
from dataclasses import dataclass
from typing import List, Optional

import structlog

from src.config import settings

logger = structlog.get_logger(__name__)


# ── Structura pentru un segment de transcript ────────────────

@dataclass
class TranscriptSegment:
    """
    Un segment = o unitate de vorbire cu timestamp de start și end.

    Whisper împarte audio-ul în segmente de ~5-15 secunde.
    Fiecare are:
    - start_time / end_time: când începe/se termină în audio (secunde)
    - text: ce s-a spus în acel interval
    - confidence: cât de sigur e modelul (0.0 = nesigur, 1.0 = sigur)
    - language: limba detectată ("ro", "en")
    """
    segment_index: int       # 0, 1, 2, ... (ordinea în transcript)
    start_time: float        # e.g. 12.500 secunde de la începutul audio
    end_time: float          # e.g. 17.320
    text: str                # e.g. "Bună ziua, doamnă primar."
    confidence: float        # 0.0 - 1.0 (calculat din avg_logprob)
    language: str            # "ro", "en", etc.


# ── WhisperTranscriber ────────────────────────────────────────

class WhisperTranscriber:
    """
    Încarcă modelul Whisper și transcrie fișiere audio.

    Fluxul tipic:
        transcriber = WhisperTranscriber()
        await transcriber.load_model()   # lent: 5-30s, o dată la startup
        segments = await transcriber.transcribe(path, "ro")  # per job
    """

    def __init__(self):
        self._model = None
        self._model_name = settings.whisper_model
        self._model_path = settings.whisper_model_path
        self._primary_language = settings.whisper_primary_language

    async def load_model(self) -> None:
        """
        Descarcă (dacă e prima dată) și încarcă modelul Whisper în RAM.

        DE CE ASYNC cu run_in_executor?
        whisper.load_model() blochează thread-ul ~5-30 secunde
        citind 1-5 GB de fișiere de pe disc în RAM + inițializând
        rețeaua neuronală PyTorch.

        Prin run_in_executor, blocarea se întâmplă în alt thread,
        nu în event loop-ul principal.

        MODEL PATH:
        download_root=str(self._model_path) → Whisper salvează modelul
        în /app/models/. Acest director e montat ca volum Docker persistent.
        La primul start: descarcă ~1.5GB (medium model) → poate dura 10+ min.
        La restart-uri ulterioare: încarcă din disc local → ~5s.
        """
        logger.info("model_loading", model=self._model_name, path=str(self._model_path))

        loop = asyncio.get_running_loop()
        self._model = await loop.run_in_executor(
            None,  # None = folosește thread pool-ul default (ThreadPoolExecutor)
            self._load_model_sync,
        )
        logger.info("model_loaded", model=self._model_name)

    def _load_model_sync(self):
        """
        Varianta sincronă a load_model() — rulată în thread pool.
        Import-ul whisper este aici (nu la nivel de modul) din 2 motive:
          1. Dacă Whisper nu e instalat, eroarea apare la load_model(), nu la import
          2. Importul lui torch durează 2-3s — nu îl facem la startup al modulului
        """
        import whisper
        return whisper.load_model(
            self._model_name,
            download_root=str(self._model_path),
        )

    async def transcribe(
        self,
        file_path: str,
        language_hint: Optional[str] = None,
    ) -> List[TranscriptSegment]:
        """
        Transcrie un fișier audio și returnează lista de segmente.

        file_path: calea completă pe disc (/data/processed/2024/03/15/uuid.mp3)
        language_hint: "ro", "en", etc. — dacă știm dinainte limba

        Tot codul CPU-intensiv rulează în _run_whisper_sync (thread pool).
        Această metodă async e doar "wrapper" care coordonează thread-ul.
        """
        if self._model is None:
            raise RuntimeError("Model neîncărcat. Apelați load_model() înainte.")

        logger.info("transcription_started", file=file_path, language=language_hint)
        loop = asyncio.get_running_loop()
        start_time = loop.time()

        segments = await loop.run_in_executor(
            None,
            self._run_whisper_sync,
            file_path,
            language_hint,
        )

        elapsed = loop.time() - start_time
        logger.info(
            "transcription_done",
            file=file_path,
            segments=len(segments),
            elapsed_sec=round(elapsed, 1),
        )
        return segments

    def _run_whisper_sync(
        self,
        file_path: str,
        language_hint: Optional[str],
    ) -> List[TranscriptSegment]:
        """
        Rulează transcrierea Whisper sincronă.
        Această metodă blochează thread-ul pe toată durata procesării.

        OPȚIUNI IMPORTANTE:
        - fp16=False: OBLIGATORIU pe CPU!
          fp16 (half-precision float16) e o optimizare pentru GPU.
          Pe CPU, torch nu suportă operații fp16 → RuntimeError.
          Dacă omitem fp16=False, Whisper încearcă fp16 automat și crăpă.

        - task="transcribe": transcrie în aceeași limbă (nu traduce)
          Alternativa: task="translate" → traduce totul în engleză

        - verbose=False: suprimă output-ul Whisper în terminal
          (altfel printează fiecare segment pe stderr)
        """
        options = {
            "task": "transcribe",
            "fp16": False,           # ← CRITICĂ pe CPU, altfel RuntimeError!
            "verbose": False,        # nu vrem spam în logs
            # no_speech_threshold: default 0.6 → creștem la 0.8 pentru a evita
            # cazurile în care Whisper clasifică greșit audioul ca non-speech.
            # Valoarea mai mare = modelul acceptă mai ușor segmente borderline.
            "no_speech_threshold": 0.8,
            # condition_on_previous_text=False: previne blocajele de tip "hallucination"
            # în care Whisper repetă același text la infinit și nu avansează în audio.
            "condition_on_previous_text": False,
        }
        if language_hint:
            options["language"] = language_hint

        result = self._model.transcribe(str(file_path), **options)

        # Convertim segmentele Whisper în dataclass-uri proprii
        return [
            self._convert_segment(raw_seg, idx, result.get("language", "ro"))
            for idx, raw_seg in enumerate(result.get("segments", []))
        ]

    def _convert_segment(self, raw: dict, idx: int, detected_language: str) -> TranscriptSegment:
        """
        Convertește un segment raw din Whisper în TranscriptSegment.

        raw["avg_logprob"]:
        Whisper returnează log-probabilitate medie per segment.
        E un număr negativ (e.g. -0.15 = bun, -1.5 = slab).
        Convertim la scară liniară [0, 1]:
            exp(-0.15) ≈ 0.86  (86% confidence)
            exp(-1.5)  ≈ 0.22  (22% confidence)

        De ce clamp la [0, 1]?
        DB coloana confidence este DECIMAL(4,3) — max valoare e 1.000.
        math.exp() poate returna 1.0001 din cauza floating point.
        Un INSERT cu 1.001 → eroare PostgreSQL "value out of range".
        """
        avg_logprob = raw.get("avg_logprob", -0.5)
        confidence = max(0.0, min(1.0, math.exp(avg_logprob)))

        # Whisper pune spațiu la începutul textului: " Bună ziua."
        # PostProcessor va face strip(), dar îl facem și aici ca siguranță
        text = raw.get("text", "").strip()

        return TranscriptSegment(
            segment_index=idx,
            start_time=float(raw.get("start", 0.0)),
            end_time=float(raw.get("end", 0.0)),
            text=text,
            confidence=round(confidence, 3),  # max 3 zecimale → DECIMAL(4,3)
            language=raw.get("language", detected_language),
        )
