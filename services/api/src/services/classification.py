# services/api/src/services/classification.py
# ============================================================
# Nivelurile de clasificare ale unei înregistrări
# ============================================================
# Codul (N, SSv, S, SS) e salvat în recordings.classification și apare în numele
# fișierelor exportate; denumirea completă apare în antetul documentelor.
# Aceeași listă: Ingest (services/ingest/src/database.py), init.sql, frontend
# (src/lib/classification.ts).
# ============================================================

from typing import Literal

ClassificationCode = Literal["N", "SSv", "S", "SS"]

DEFAULT_CLASSIFICATION: ClassificationCode = "N"

# În ordinea crescătoare a sensibilității
CLASSIFICATION_LABELS: dict[str, str] = {
    "N": "NECLASIFICAT",
    "SSv": "SECRET DE SERVICIU",
    "S": "SECRET",
    "SS": "STRICT SECRET",
}


def classification_label(code: str) -> str:
    return CLASSIFICATION_LABELS.get(code, CLASSIFICATION_LABELS[DEFAULT_CLASSIFICATION])
