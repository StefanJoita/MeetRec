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

import hashlib
import json
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

# Valorile tipului audio_format din baza de date (în afară de 'unknown')
KNOWN_AUDIO_FORMATS = {"wav", "mp3", "m4a", "mp4", "ogg", "flac", "webm"}

# Nivelurile de clasificare (aceeași listă ca în API: services/classification.py).
# Fișierele copiate direct în inbox, fără nivel, devin N.
CLASSIFICATIONS = {"N", "SSv", "S", "SS"}

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
    
    async def get_app_setting(self, key: str) -> Any:
        """Valoarea setată din Administrare → Setări (tabelul app_settings), sau None."""
        async with self._pool.acquire() as conn:
            try:
                raw = await conn.fetchval("SELECT value FROM app_settings WHERE key = $1", key)
            except asyncpg.UndefinedTableError:
                return None          # API-ul n-a aplicat încă migrarea 010
        return json.loads(raw) if isinstance(raw, str) else raw

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

        meeting_date_val = self._meeting_date(meta)

        description: Optional[str] = meta.get("description")
        location: Optional[str] = meta.get("location")
        participants: Optional[List[str]] = meta.get("participants")  # list[str] sau None
        session_id_val: Optional[str] = meta.get("session_id")  # UUID string sau None

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
                        session_id,
                        last_segment_at,
                        status,
                        classification
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18
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
                    uuid.UUID(session_id_val) if session_id_val else None,
                    # last_segment_at: setat doar pentru sesiuni (nu și pentru upload-uri simple)
                    # Session Watcher verifică acest câmp pentru a decide când să lanseze transcrierea
                    datetime.now(timezone.utc) if session_id_val else None,
                    "queued",
                    self._classification(meta),
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

                # Fișier copiat direct în inbox (fără API): singura urmă în jurnalul de audit.
                # Încărcările prin API sunt jurnalizate de API (sidecar cu uploaded_via).
                if not meta.get("uploaded_via") and not session_id_val:
                    await conn.execute(
                        """
                        INSERT INTO audit_logs (id, action, resource_type, resource_id, details, success, user_ip)
                        VALUES ($1, 'UPLOAD', 'recording', $2, $3, true, '127.0.0.1')
                        """,
                        str(uuid.uuid4()),
                        recording_id,
                        json.dumps({
                            "resource_name": final_title,
                            "filename": metadata.filename,
                            "size_bytes": metadata.file_size_bytes,
                            "sha256": metadata.file_hash_sha256,
                            "source": "inbox_folder",
                        }, ensure_ascii=False),
                    )

        logger.info(
            "recording_created",
            recording_id=recording_id,
            title=final_title,
            duration_sec=metadata.duration_seconds,
        )
        return recording_id
 
    async def create_rejected_recording(
        self,
        filename: str,
        file_path: Path,
        file_size_bytes: int,
        error_message: str,
        user_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Înregistrare cu status 'failed' pentru un fișier respins la validare, ca
        utilizatorul să vadă în listă că fișierul a ajuns și de ce a fost respins
        (altfel încărcarea pare reușită și „nu se întâmplă nimic”).

        Fără transcript: nu există nimic de reîncercat (interfața ascunde butonul).
        Hash-ul e unul de completare, NU al fișierului: după corectarea problemei,
        același fișier trebuie să poată fi încărcat din nou fără să fie luat drept duplicat.
        """
        recording_id = str(uuid.uuid4())
        meta = user_meta or {}
        extension = Path(filename).suffix.lower().lstrip(".")
        audio_format = extension if extension in KNOWN_AUDIO_FORMATS else "unknown"
        title = meta.get("title") or self._generate_title(filename)

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO recordings (
                    id, title, meeting_date, description, location, participants,
                    original_filename, file_path, file_size_bytes, file_hash_sha256,
                    audio_format, status, error_message, classification
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'failed', $12, $13)
                """,
                recording_id,
                title,
                self._meeting_date(meta),
                meta.get("description"),
                meta.get("location"),
                meta.get("participants"),
                filename,
                str(file_path),
                file_size_bytes,
                hashlib.sha256(f"rejected:{recording_id}".encode()).hexdigest(),
                audio_format,
                error_message,
                self._classification(meta),
            )
        logger.info("rejected_recording_created", recording_id=recording_id, filename=filename)
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

    async def get_recording_status(self, recording_id: str) -> Optional[str]:
        """Returnează status-ul unui Recording după id, sau None dacă nu există."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT status FROM recordings WHERE id = $1",
                recording_id,
            )
            return row["status"] if row else None

    async def find_recording_by_session_id(self, session_id: str) -> Optional[str]:
        """
        Returnează recording_id-ul înregistrării principale a unei sesiuni, sau None.
        Folosit de processor pentru a decide dacă să creeze o înregistrare nouă
        sau să atașeze un segment la una existentă.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM recordings WHERE session_id = $1",
                session_id,
            )
            return str(row["id"]) if row else None

    async def create_audio_segment(
        self,
        recording_id: str,
        segment_index: int,
        stored_path: Path,
        metadata: "AudioMetadata",
    ) -> str:
        """
        Atașează un fișier audio suplimentar la o înregistrare existentă.
        Returnează id-ul segmentului creat.
        """
        import uuid as _uuid
        segment_id = str(_uuid.uuid4())
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO recording_audio_segments
                        (id, recording_id, segment_index, file_path,
                         file_hash_sha256, file_size_bytes, duration_seconds, status)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, 'queued')
                    """,
                    segment_id,
                    recording_id,
                    segment_index,
                    str(stored_path),
                    metadata.file_hash_sha256,
                    metadata.file_size_bytes,
                    metadata.duration_seconds,
                )
                # Durata înregistrării = tot audio-ul primit până acum. Altfel, până
                # la finalul transcrierii (când STT Worker scrie suma), o ședință de
                # 6 min 30 s apare cu durata primului segment (5 min).
                await conn.execute(
                    """
                    UPDATE recordings
                    SET duration_seconds = COALESCE(duration_seconds, 0) + $2,
                        updated_at = NOW()
                    WHERE id = $1
                    """,
                    recording_id,
                    metadata.duration_seconds,
                )
        logger.info(
            "audio_segment_attached",
            recording_id=recording_id,
            segment_index=segment_index,
            segment_id=segment_id,
        )
        return segment_id

    async def update_primary_file(
        self,
        recording_id: str,
        metadata: "AudioMetadata",
        stored_path: "Path",
    ) -> None:
        """
        Actualizează câmpurile audio ale unui Recording pre-înregistrat (status='session_registered')
        cu datele reale ale primului segment audio. Setează status='queued' după update.

        Apelat de Processor când segmentul 0 sosește pentru o sesiune pre-înregistrată via API.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE recordings
                SET
                    original_filename  = $1,
                    file_path          = $2,
                    file_size_bytes    = $3,
                    file_hash_sha256   = $4,
                    audio_format       = $5,
                    -- plus segmentele sosite înaintea segmentului 0 (încărcări în paralel)
                    duration_seconds   = $6 + COALESCE((
                        SELECT SUM(duration_seconds) FROM recording_audio_segments
                        WHERE recording_id = $9
                    ), 0),
                    sample_rate_hz     = $7,
                    channels           = $8,
                    status             = 'queued',
                    last_segment_at    = NOW(),
                    updated_at         = NOW()
                WHERE id = $9
                """,
                metadata.filename,
                str(stored_path),
                metadata.file_size_bytes,
                metadata.file_hash_sha256,
                metadata.audio_format,
                metadata.duration_seconds,
                metadata.sample_rate_hz,
                metadata.channels,
                recording_id,
            )
        logger.info(
            "primary_file_updated",
            recording_id=recording_id,
            filename=metadata.filename,
            duration_sec=metadata.duration_seconds,
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

    async def update_last_segment_at(self, recording_id: str) -> None:
        """
        Actualizează last_segment_at la NOW() pentru o înregistrare de sesiune.
        Apelat de fiecare dată când un segment nou este primit și stocat.
        Session Watcher folosește acest câmp pentru a calcula timeout-ul.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE recordings
                SET last_segment_at = NOW()
                WHERE id = $1
                """,
                recording_id,
            )

    async def find_expired_sessions(self, timeout_seconds: int) -> List[str]:
        """
        Returnează recording_id-urile sesiunilor care nu au primit segmente noi
        de cel puțin timeout_seconds secunde și sunt încă în status 'queued'.

        Acestea sunt sesiunile gata de transcriere — clientul a terminat de trimis.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id FROM recordings
                WHERE session_id IS NOT NULL
                  AND status = 'queued'
                  AND last_segment_at IS NOT NULL
                  AND last_segment_at < NOW() - ($1 || ' seconds')::INTERVAL
                ORDER BY last_segment_at ASC
                """,
                str(timeout_seconds),
            )
            return [str(row["id"]) for row in rows]

    async def mark_session_dispatched(self, recording_id: str) -> None:
        """
        Marchează sesiunea ca 'transcribing' ÎNAINTE de a publica jobul în Redis.
        Previne ca Session Watcher să dispatcheze aceeași sesiune de două ori
        (ex: dacă watcher rulează în timp ce jobul e deja în Redis).
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE recordings
                SET status = 'transcribing', last_segment_at = NULL
                WHERE id = $1
                """,
                recording_id,
            )
        logger.info("session_dispatched_to_transcription", recording_id=recording_id)

    @staticmethod
    def _classification(meta: Dict[str, Any]) -> str:
        """Nivelul de clasificare din user_meta; necunoscut sau lipsă → N."""
        value = meta.get("classification")
        return value if value in CLASSIFICATIONS else "N"

    @staticmethod
    def _meeting_date(meta: Dict[str, Any]) -> date:
        """Data ședinței din user_meta (YYYY-MM-DD); altfel azi."""
        raw_date = meta.get("meeting_date")
        if raw_date:
            try:
                return date.fromisoformat(raw_date)
            except ValueError:
                pass
        return datetime.now(timezone.utc).date()

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
       