# services/stt-worker/src/cancellation.py
# ============================================================
# Anularea unei transcrieri în curs
# ============================================================
# API-ul cere anularea punând cheia "transcription:cancel:<recording_id>"
# în Redis (din Administrare → Coadă, sau la ștergerea înregistrării).
# Worker-ul o verifică la câteva secunde și setează un threading.Event.
#
# Transcrierea rulează într-un fir care nu poate fi oprit din afară, dar
# WhisperX apelează callback-ul de progres după fiecare lot (transcriere,
# aliniere, diarizare): acolo aruncăm JobCancelled, iar etapa se oprește
# fără ca modelele să fie descărcate din memorie.
#
# Prefixul cheii trebuie să fie identic cu cel din services/api (queue_service.py).
# ============================================================

import threading
from typing import Optional

CANCEL_KEY_PREFIX = "transcription:cancel:"


def cancel_key(recording_id: str) -> str:
    return f"{CANCEL_KEY_PREFIX}{recording_id}"


class AnyEvent:
    """Setat când oricare dintre evenimente e setat (anularea jobului sau oprirea internă a unei etape)."""

    def __init__(self, *events: Optional[threading.Event]):
        self._events = [e for e in events if e is not None]

    def is_set(self) -> bool:
        return any(e.is_set() for e in self._events)


class JobCancelled(Exception):
    """Transcrierea a fost anulată (din interfață sau prin ștergerea înregistrării)."""


def raise_if_cancelled(cancel: Optional[threading.Event]) -> None:
    if cancel is not None and cancel.is_set():
        raise JobCancelled()
