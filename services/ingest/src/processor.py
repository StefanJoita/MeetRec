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
from pathlib import Path

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
        
        # ── Pasul 4: Înregistrare în DB ───────────────────────────────
        try: 
             recording_id = await self.database.create_recording(
                metadata=metadata,
                stored_path=stored_path,
             )
        except Exception as e:
             logger.error("database_error",file=file_path.name,error=str(e))
             #Rollback manual: stergem fisierul mutat daca DB a esuat
             self.storage.delete_file(stored_path)
             return False   
        
        # ── Pasul 5: Publicare job de transcriere ─────────────────────
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
            # NU facem rollback: fișierul e în DB cu status='queued'
            # Un job de recovery poate republica mai târziu
            # (e mai bine decât să ștergem tot)
 
        logger.info(
            "processing_completed",
            file=file_path.name,
            recording_id=recording_id,
            duration_sec=metadata.duration_seconds,
            size_mb=round(metadata.file_size_bytes / 1024 / 1024, 2),
            stored_at=str(stored_path),
        )
        return True
