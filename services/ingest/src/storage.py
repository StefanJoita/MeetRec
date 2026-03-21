# services/ingest/src/storage.py
# ============================================================
# Storage Manager — Organizează fișierele pe NFS/disc
# ============================================================
# Strategie de organizare a fișierelor:
#
# /data/processed/
#   └── 2024/           ← an
#       └── 01/         ← lună  
#           └── 15/     ← zi
#               └── a3f4c2b1-uuid-complet.mp3
#
# De ce organizăm pe dată și nu punem totul într-un folder?
# - Un folder cu 10.000 fișiere devine lent pe orice sistem de fișiere
# - Retenție ușoară: "șterge tot din 2021/" = o comandă
# - Backup incremental: "backup-ează doar 2024/01/" = eficient
# ============================================================
import os
import shutil
import uuid
from pathlib import Path
from datetime import datetime, timezone

from src.config import settings
from src.logger import get_logger
from src.validator import AudioMetadata

logger = get_logger(__name__)

API_RUNTIME_UID = 1000
API_RUNTIME_GID = 1000

class StorageManager:
    """
    Gestioneaza mutarea si organizarea fisierelor audio.
    """
    
    def store_file(self,metadata:AudioMetadata) -> Path:
        """
        Muta un fisier validat din inbox in storage organizat.
        Args:
            metadata: Metadata extrasa de validator
        Return: 
            Path-ul nou al fisierului in storage
        Raises: 
            StorageError: daca mutarea esueaza
        """
        #Construim calea destinatie
        destination=self.build_destination_path(
            metadata.file_path,
            metadata.audio_format
        )

        #Cream directoarele intermediare daca nu exista
        #parents=True : creeaza si /data/processed/2024/01/15 deodata

        destination.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_api_write_access(destination.parent)

        logger.info(
            "storing_file",
            source=str(metadata.file_path),
            destination= str(destination),
        )
        try:
            #shutil.move = muta fisierul (rename daca e pe acelasi filesystem,
            #copy+delete daca intre fs uri diferite)
            #pe NFS: va face copy+delete automat
            shutil.move(str(metadata.file_path),str(destination))
            os.chown(destination, API_RUNTIME_UID, API_RUNTIME_GID)
            destination.chmod(0o664)

            logger.info("file_stored",path=str(destination))
            return destination
        
        except(OSError,shutil.Error) as e:
            logger.error("storage_failed",
            source=str(metadata.file_path),
            destination=str(destination),
            error=str(e)
            )
            raise StorageError(f"Nu am putut muta fisierul : {e}") from e
    
    def build_destination_path(
        self,
        source_path:Path,
        extension:str
    )->Path: 
        """
        Construieste calea destinatie organizata pe data.
        Exemplu: source: data/inbox/Sedinta_Consiliu.mp3
                 destination: data/processed/2024/01/15/a3f4c2b1-uuid-complet.mp3
        Folim un UUID pentru a evita coliziunile de nume (ex: 2 sedinte cu acelasi nume)         
        """
        now=datetime.now(timezone.utc)
        #Structura de directoare: an/luna/zi
        date_path=Path(
            str(now.year),
            f"{now.month:02d}",
            f"{now.day:02d}" #zzero-padding pentru luna si zi (ex: 01, 02, ..., 12)
        )
        #generam un UUID unic pentru fisier
        file_uuid=str(uuid.uuid4())
        #constuim calea completa
        destination=(
            settings.audio_storage_path / date_path / f"{file_uuid}.{extension}"
        )
        return destination

    def _ensure_api_write_access(self, directory: Path) -> None:
        """
        Asigură că API-ul poate șterge ulterior fișierele din structura pe zile.
        Ingest rulează ca root în container, iar API ca uid/gid 1000.
        """
        storage_root = settings.audio_storage_path.resolve()
        target_dir = directory.resolve()

        if storage_root not in (target_dir, *target_dir.parents):
            raise StorageError(f"Calea {target_dir} nu este în storage-ul configurat.")

        current = storage_root
        os.chown(current, API_RUNTIME_UID, API_RUNTIME_GID)
        current.chmod(0o775)

        for part in target_dir.relative_to(storage_root).parts:
            current = current / part
            os.chown(current, API_RUNTIME_UID, API_RUNTIME_GID)
            current.chmod(0o775)
    
    def delete_file(self, file_path: Path) -> bool:
        """
        Șterge un fișier (pentru retenție sau cleanup erori).
        Returns True dacă a fost șters, False dacă nu exista.
        """
        if not file_path.exists():
            logger.warning("delete_file_not_found", path=str(file_path))
            return False
 
        try:
            file_path.unlink()  # unlink = șterge fișierul
            logger.info("file_deleted", path=str(file_path))
            return True
        except OSError as e:
            logger.error("delete_failed", path=str(file_path), error=str(e))
            raise StorageError(f"Nu am putut șterge fișierul: {e}") from e
 
    def move_to_error(self, file_path: Path) -> Path:
        """
        Mută un fișier invalid în /data/inbox/errors/ pentru inspecție manuală.
        Nu ștergem fișierele invalide — poate vrea cineva să le inspecteze.
        """
        error_dir = settings.inbox_path / "errors"
        error_dir.mkdir(exist_ok=True)
 
        destination = error_dir / file_path.name
        # Dacă există deja un fișier cu același nume în errors/, adăugăm timestamp
        if destination.exists():
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            destination = error_dir / f"{file_path.stem}_{timestamp}{file_path.suffix}"
 
        shutil.move(str(file_path), str(destination))
        logger.info("file_moved_to_error", path=str(destination))
        return destination
 
 
class StorageError(Exception):
    """Excepție specifică pentru erori de storage."""
    pass