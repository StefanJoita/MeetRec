#services/ingest/src/processor.py
# ============================================================
# File Processor — Orchestratorul procesarii uni fisier audio
# ============================================================
#Coordoneaza: Validator->Storage->Database->Publisher
# ============================================================
# Processor e clasa care "leagă" toate componentele.
# Ea primește un fișier nou, îl validează, îl stochează,    
# îl înregistrează în DB și îl trimite la coadă.
# Astfel, restul componentelor (validator, storage, db, publisher)
# rămân simple și se ocupă doar de responsabilitatea lor.
# ============================================================
#Design Pattern: Facade
# Processor ascunde complexitatea (4 servicii, error handling,
# logging) în spatele unui singur apel: processor.process(file)
# ============================================================
import json
from pathlib import Path
from typing import Any, Dict

from src.config import settings
from src.logger import get_logger
from src.validator import AudioMetadata, AudioValidator
from src.storage import StorageError, StorageManager
from src.database import DatabaseClient
from src.publisher import JobPublisher, TranscriptionJob

logger=get_logger(__name__)

class FileProcessor:
    """
    Orchestreaza proceasarea completa a unui fisier audio nou.
    Injectie de dependinte (Dependency Injection) 101:
    iN Loc sa cream DatabaseClient() in interiorul clasei,
    il primim ca parametru. Avantaje:
    -Testabilitate: in teste pasam un fake database client
    -Flexabilitate: putim schimba implementarea fara sa modificam FileProcessor
    """
    def __init__ ( 
            self,
            validator: AudioValidator,
            storage:StorageManager,
            database:DatabaseClient,
            publisher:JobPublisher,
    ):
            self.validator=validator
            self.storage=storage
            self.database=database
            self.publisher=publisher
    

    async def process(self, file_path: Path) -> bool:
        """
        Procesează un fișier audio: validează, stochează, înregistrează, publică.
        
        Returns:
            True dacă procesarea a reușit, False altfel
        """
        logger.info("processing_started", file=file_path.name)

        # ── Sidecar: metadate furnizate de utilizator la upload ─
        user_meta: Dict[str, Any] = {}
        sidecar_path = file_path.with_suffix(file_path.suffix + ".meetrec-meta.json")
        if sidecar_path.exists():
            try:
                user_meta = json.loads(sidecar_path.read_text(encoding="utf-8"))
                logger.info("sidecar_loaded", file=file_path.name, keys=list(user_meta.keys()))
            except Exception as e:
                logger.warning("sidecar_read_failed", file=file_path.name, error=str(e))
            finally:
                sidecar_path.unlink(missing_ok=True)

        # ── Pasul 1: Validare ──────────────────────────────────
        result = self.validator.validate(file_path)
 
        if not result.is_valid:
            logger.warning(
                "file_rejected",
                file=file_path.name,
                reason=result.error_code,
                message=result.error_message,
            )
            # Mutăm fișierul invalid în /errors/ pentru inspecție
            self.storage.move_to_error(file_path)
            return False
 
        metadata = result.metadata  # AudioMetadata cu toate detaliile
 
        # ── Pasul 2: Verificare duplicate ─────────────────────
        existing_id = await self.database.check_duplicate(
            metadata.file_hash_sha256
        )
        if existing_id:
            logger.warning(
                "duplicate_rejected",
                file=file_path.name,
                existing_recording_id=existing_id,
            )
            # Ștergem duplicatul din inbox (nu îl mutăm în errors)
            file_path.unlink(missing_ok=True)
            return False
        
        # ── Pasul 3: Stocare pe NFS ──────────────────────────────────
        try:
             stored_path = self.storage.store_file(metadata)

        except StorageError as e:
            logger.error(
                "storage_failed",
                file=file_path.name,
                error=str(e),
            )
            return False

        # ── Pasul 4: Sesiune existentă vs. înregistrare nouă ─────────
        # Dacă sidecar-ul conține existing_recording_id (setat de API când
        # session_id e deja cunoscut), atașăm fișierul ca segment suplimentar.
        existing_recording_id = user_meta.get("existing_recording_id")
        session_id = user_meta.get("session_id")
        segment_index = user_meta.get("segment_index", 0)

        # Race condition fix: dacă session_id e prezent dar existing_recording_id
        # lipsește din sidecar, înseamnă că API-ul a scris sidecarul înainte ca
        # ingest să fi creat Recording-ul pentru segmentul 0. Facem lookup în DB
        # — dacă Recording-ul există deja, atașăm ca segment, nu creăm duplicat.
        if session_id and not existing_recording_id:
            existing_recording_id = await self.database.find_recording_by_session_id(session_id)
            if existing_recording_id:
                logger.info(
                    "session_recovery_via_db_lookup",
                    file=file_path.name,
                    session_id=session_id,
                    recording_id=existing_recording_id,
                )

        if existing_recording_id:
            return await self._attach_segment(
                existing_recording_id=existing_recording_id,
                segment_index=segment_index,
                stored_path=stored_path,
                metadata=metadata,
                file_path=file_path,
            )

        # ── Pasul 5: Creare înregistrare nouă ────────────────────────
        try:
             recording_id = await self.database.create_recording(
                metadata=metadata,
                stored_path=stored_path,
                user_meta=user_meta,
             )
        except Exception as e:
             logger.error("database_error",file=file_path.name,error=str(e))
             #Rollback manual: stergem fisierul mutat daca DB a esuat
             self.storage.delete_file(stored_path)
             return False

        # ── Pasul 6: Publicare job de transcriere ─────────────────────
        # Dacă înregistrarea face parte dintr-o sesiune multi-segment (session_id prezent),
        # NU publicăm job imediat — Session Watcher va publica UN SINGUR job după timeout,
        # după ce toate segmentele au sosit. Astfel Whisper transcrie audio-ul concatenat,
        # nu bucăți individuale (artefacte la joncțiuni).
        if session_id:
            logger.info(
                "session_recording_waiting",
                recording_id=recording_id,
                session_id=session_id,
            )
            return True

        try:
             self.publisher.publish_transcription_job(
                recording_id=recording_id,
                metadata=metadata,
                stored_path=stored_path
             )
        except Exception as e:
            logger.error(
                "publish_error",
                recording_id=recording_id,
                error=str(e),
            )
            # Marcăm ca failed — altfel înregistrarea rămâne blocată în 'queued'
            # fără niciun job în coadă și fără feedback pentru utilizator.
            await self.database.mark_failed_by_id(
                recording_id=recording_id,
                error_message=f"Redis unavailable: {e}",
            )
            return False

        logger.info(
            "processing_completed",
            file=file_path.name,
            recording_id=recording_id,
            duration_sec=metadata.duration_seconds,
            size_mb=round(metadata.file_size_bytes / 1024 / 1024, 2),
            stored_at=str(stored_path),
        )
        return True

    async def _attach_segment(
        self,
        existing_recording_id: str,
        segment_index: int,
        stored_path: "Path",
        metadata: "AudioMetadata",
        file_path: "Path",
    ) -> bool:
        """
        Atașează un fișier audio ca segment suplimentar la o înregistrare existentă.
        Creează o intrare în recording_audio_segments și publică un job de transcriere
        cu referință la segmentul specific.
        """
        try:
            segment_id = await self.database.create_audio_segment(
                recording_id=existing_recording_id,
                segment_index=segment_index,
                stored_path=stored_path,
                metadata=metadata,
            )
        except Exception as e:
            logger.error(
                "segment_attach_failed",
                file=file_path.name,
                recording_id=existing_recording_id,
                error=str(e),
            )
            self.storage.delete_file(stored_path)
            return False

        # Actualizăm last_segment_at — Session Watcher măsoară timeout-ul de la acest moment.
        # NU publicăm job Redis: Session Watcher va publica UN SINGUR job după timeout,
        # când toate segmentele au sosit și sunt gata de concatenat.
        await self.database.update_last_segment_at(existing_recording_id)

        logger.info(
            "segment_attached",
            file=file_path.name,
            recording_id=existing_recording_id,
            segment_index=segment_index,
            segment_id=segment_id,
        )
        return True
