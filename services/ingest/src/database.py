# services/ingest/src/database.py
# ============================================================
# Database Client — Înregistrează fișierele în PostgreSQL
# ============================================================
# Ingest Service scrie în DB de două ori per fișier:
#   1. La primire: status='queued' (fișierul e în coadă)
#   2. La eroare: status='failed' cu mesajul de eroare
#
# STT Worker va face update la status='completed' când termină.
# ============================================================

import uuid
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import asyncpg
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import settings
from src.logger import get_logger
from src.validator import AudioMetadata 

logger=get_logger(__name__  )

class DatabaseClient:
    """Client pentru operatiile de baza de date ale Ingest Service.
    Folosim asyncpg direct (fara ORM) pentru simplitate in aceast serviciu"""

    def __init__(self):
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        """Creaza connection pool la PostgreSQL
        Connection pool 101: 
        -Crearea unei conexiunui la db dureaza ~100ms
        -Daca cream o conexiune noua pentru fiecare query -> lent
        -Pool = tinem 5-10 conexiuni deschise, le refolosim pentru fiecare query
        -Cand avem nevoie : ''imprumutam'' o conexiune din pool, o folosim, apoi o returnam la pool
        """
        logger.info("connecting_to_db")
        self._pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=2,#minim 2 conexiuni in pool
            max_size=10,#maxim 10 conexiuni in pool
            command_timeout=30, #timeout pentru fiecare query
        )
        logger.info("database_connected")
    
    async def disconnect(self):
        """Inchide toate conexiunle la shutdown"""
        if self._pool:
            await self._pool.close()
            logger.info("database_disconnected")
    
    async def check_duplicate(self, file_hash:str)->Optional[str]:
        """Verifica daca exista deja un fisier cu acelasi hash in DB
        Args:
            file_hash: hash-ul fisierului (ex: SHA256)
        Return:
            recording_id daca exista duplicat, altfel None
        
        """
        async with self._pool.acquire() as conn:
            #acquire() = "imprumutam" o conexiune din pool
            row = await conn.fetchrow(
                """
                SELECT id, title, created_at
                FROM recordings
                WHERE file_hash_sha256=$1""",
                file_hash#$1=primul parametru dupa query, parametru pozitional (previne sql injection)
                #niciodata : f"SELECT * FROM recordings WHERE file_hash='{file_hash}'" (vulnerabil la sql injection)
                )
            if row:
                logger.warning(
                    "duplicate_detected",
                    hash=file_hash[:16], 
                    existing_id=str(row["id"]),
                    existing_title=row["title"],
                )
                return str(row["id"])
            return None

    async def create_recording(
        self,
        metadata: AudioMetadata,
        stored_path: Path,
        title: Optional[str] = None,
        user_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Insereaza o inregistrare noua in baza de date.

        Returneaza recording_id-ul generat (UUID) pentru inregistrarea noua.
        user_meta poate conține: title, meeting_date, description, participants, location.
        """
        recording_id = str(uuid.uuid4())
        meta = user_meta or {}

        # Titlu: din user_meta → din parametrul title → generat din filename
        final_title = meta.get("title") or title or self._generate_title(metadata.filename)

        # Data ședinței: din user_meta (YYYY-MM-DD) → azi
        meeting_date_val: date
        raw_date = meta.get("meeting_date")
        if raw_date:
            try:
                meeting_date_val = date.fromisoformat(raw_date)
            except ValueError:
                meeting_date_val = datetime.now(timezone.utc).date()
        else:
            meeting_date_val = datetime.now(timezone.utc).date()

        description: Optional[str] = meta.get("description")
        location: Optional[str] = meta.get("location")
        participants: Optional[List[str]] = meta.get("participants")  # list[str] sau None

        async with self._pool.acquire() as conn:
            # Folosim tranzactie pentru atomicitate:
            # fie INSERT-urile reusesc amandoua, fie niciuna.
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO recordings (
                        id,
                        title,
                        meeting_date,
                        description,
                        location,
                        participants,
                        original_filename,
                        file_path,
                        file_size_bytes,
                        file_hash_sha256,
                        audio_format,
                        duration_seconds,
                        sample_rate_hz,
                        channels,
                        status
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15
                    )
                    """,
                    recording_id,
                    final_title,
                    meeting_date_val,
                    description,
                    location,
                    participants,
                    metadata.filename,
                    str(stored_path),
                    metadata.file_size_bytes,
                    metadata.file_hash_sha256,
                    metadata.audio_format,
                    metadata.duration_seconds,
                    metadata.sample_rate_hz,
                    metadata.channels,
                    "queued",
                )

                # Cream si intrarea transcript asociata (in starea pending).
                await conn.execute(
                    """
                    INSERT INTO transcripts (id, recording_id, status, language)
                    VALUES ($1, $2, 'pending', 'ro')
                    """,
                    str(uuid.uuid4()),
                    recording_id,
                )

        logger.info(
            "recording_created",
            recording_id=recording_id,
            title=final_title,
            duration_sec=metadata.duration_seconds,
        )
        return recording_id
 
    async def mark_failed(self, file_hash: str, error_message: str) -> None:
        """
        Marchează o înregistrare ca eșuată.
        Apelat când validarea pică sau mutarea fișierului eșuează.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE recordings
                SET status = 'failed', error_message = $1, updated_at = NOW()
                WHERE file_hash_sha256 = $2
                """,
                error_message,
                file_hash,
            )

    async def mark_failed_by_id(self, recording_id: str, error_message: str) -> None:
        """
        Marchează o înregistrare ca eșuată după ID.
        Apelat când publicarea în Redis eșuează după ce înregistrarea a fost creată în DB.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE recordings
                SET status = 'failed', error_message = $1, updated_at = NOW()
                WHERE id = $2
                """,
                error_message,
                recording_id,
            )

    @staticmethod
    def _generate_title(filename: str) -> str:
        """
        Generează un titlu lizibil din numele fișierului.
        
        Exemple:
            "sedinta_consiliu_15ian2024.mp3" → "Sedinta Consiliu 15Ian2024"
            "SEDINTA-2024-01-15.wav" → "Sedinta 2024 01 15"
        """
        # Eliminăm extensia
        stem = Path(filename).stem
 
        # Înlocuim separatorii cu spații
        title = stem.replace("_", " ").replace("-", " ")
 
        # Title case: prima literă din fiecare cuvânt mare
        title = title.title()
 
        # Prefix dacă titlul e prea scurt sau neclar
        if len(title) < 3:
            title = f"Înregistrare {datetime.now(timezone.utc).strftime('%d %b %Y')}"
 
        return title[:500]  # maxim 500 caractere (limita din DB)
       