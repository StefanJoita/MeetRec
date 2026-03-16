# services/ingest/src/validator.py
# ============================================================
# Validator — Verifică fișierele audio înainte de procesare
# ============================================================
# Principiul "Fail Fast":
# Mai bine respingem un fișier invalid ACUM (la ingestie)
# decât să trimitem gunoi la STT Worker și să descoperim
# problema după 30 de minute de procesare.
# ============================================================

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional 

import mutagen  

from src.config import settings
from src.logger import get_logger

logger=get_logger(__name__)

#=================================================================
# DATA CLASSES - Structuri de date simple
#=================================================================
# @dataclass: decorator care adauga automat metode ca __init__, __repr__, __eq__
#ne scute de boilerplate si face codul mai curat
@dataclass
class AudioMetadata:
    """Metadata extrasa dintr-un fisier audio valid.
    Aceasta structura circula prin tot serviciul.
    """
    filename: str
    file_path : Path
    file_size_bytes: int
    file_hash_sha256: str
    audio_format: str #mp3, wav, etc.
    duration_seconds: int
    sample_rate_hz: Optional[int] = None
    channels: Optional[int] = None
    bitrate_kbps: Optional[int] = None

@dataclass
class ValidationResult:
    """Rezultatul validarii unui fisier audio.
    """
    is_valid:bool
    error_code : Optional[str] = None
    error_message: Optional[str] = None
    metadata: Optional[AudioMetadata] = None


#=================================================================
# VALIDATOR - Logica de validare a fisierelor audio
#=================================================================  

class AudioValidator:
    """
    Validează fișierele audio în mai mulți pași.    
    Pași de validare (în ordine, de la cel mai ieftin la cel mai scump):
    1. Verificare extensie (instant)
    2. Verificare dimensiune (instant)
    3. Verificare că fișierul există și e accesibil (instant)
    4. Calculare hash SHA256 (citește tot fișierul - câteva secunde)
    5. Extragere metadata audio (deschide fișierul - câteva secunde)
    6. Verificare că poate fi decodat (costisitor - evitat dacă posibil)
        
    De ce această ordine? Principiul "Cheapest Check First":
    Dacă extensia e greșită, nu calculăm hash-ul inutil.
    """
        
    def validate(self, file_path: Path) -> ValidationResult:
        """
        Punct de intrare principal. Ruleaza toti pasii de validare
        Returns: 
        ValidationResult cu metadate daca valid,
        sau cu error_code/error_message daca invalid
        """
        logger.info("validation_started",file=str(file_path))
        #--- Pasul 1: Fisierul exista? ---
        if not file_path.exists():
            return self._reject("FILE_NOT_FOUND", f"Fisierul nu exista: {file_path}")
        if not file_path.is_file():
            return self._reject("NOT_A_FILE", f"Calea nu este un fisier: {file_path}")
        
        #---Pasul 2: Extensie valida?---
        extension=file_path.suffix.lower().lstrip(".") #ex: ".mp3" -> "mp3"
        if extension not in settings.allowed_audio_formats:
            return self._reject(
                "INVALID_FORMAT",
                f"format nesuportat: .{extension}."
                f"Formate acceptate: {settings.allowed_audio_formats}"
            )
        
        #---Pasul 3: Dimensiune acceptabila?---
        file_size=file_path.stat().st_size #dimensiune in bytes
        if file_size==0:
            return self._reject("FILE_EMPTY", "Fisierul este gol (0 bytes)")
        
        
        if file_size > settings.max_file_size_bytes:
            self_mb=file_size/(1024*1024)
            max_mb=settings.max_file_size_bytes/(1024*1024)

            return self._reject(
                "FILE_TOO_LARGE",
                f"Fisierul depaseste dimensiunea maxima acceptata: {self_mb:.2f} MB > {max_mb:.2f} MB"
            )
        
        #---Pasul 4: Calculare hash SHA256---
        #Hashul e amprenta digitala a fisierului. Daca acelasi fisier e uploadat de 2 ori, hashul va fi acelasi.
        try:    
            file_hash=self._calculate_sha256(file_path)
        except OSError as e:
            return self._reject("READ_ERROR", f"Nu pot citi fișierul: {e}")

        #--- Pasul 5: Extragere metadata audio ---
        metadata_result=self._extract_audio_metadata(
            file_path,extension,file_size,file_hash
        )
        if not metadata_result.is_valid:
            return metadata_result #contine error_code si error_message
        
        logger.info(
            "validation_success",
            size_mb=round(file_size/1024/1024,2),
            duration_sec=metadata_result.metadata.duration_seconds,
            format=extension
        )
        return metadata_result #contine metadata audio valid
    
    #=========================================================
    #Metode private - nu sunt expuse in afara clasei
    #convingere: _ prefix = "intern. nu folosi direct"
    #=========================================================
    def _calculate_sha256(self,file_path: Path) -> str:
        """Calculeaza hash SHA256 al fisierului.
        SHA256 101:
        -Orice modificare in fisier=> hash complet diferit.
        -Imposibil sa reconstruiesti fisierul din hash
        -2 fisiere diferite => hash diferit (coliziuni extrem de rare)
        
        Citim in chunks de 8MB pentru a nu incarca tot fisierul in memorie (important pentru fisiere mari). 

        """
        sha256=hashlib.sha256()
        chunk_size=8*1024*1024 #8MB
        with file_path.open("rb") as f: #rb = read binary
            while chunk := f.read(chunk_size):
                sha256.update(chunk) # := = walrus operator (Python 3.8+)
                #chunk :=f.read() citeste chunk si asigneaza la variabila
                #while chunk: continua cat timp chunk nu e gol (EOF)

        return sha256.hexdigest()
    
    def _extract_audio_metadata(
        self,
        file_path: Path,
        extension: str,
        file_size: int,
        file_hash: str,
    ) -> ValidationResult:
        """
        Extrage metadata audio folosind mutagen
        Mutagen citeste header-ele fisierului fara sa decodeze audio
        """
        try:
            audio=mutagen.File(file_path,easy=True)
            
            if audio is None:
                #mutagen nu a recunoscut fisierul
                return self._reject(
                    "UNREADABLE_AUDIO"
                    "Fisierul nu poate fi citit ca audio"
                    "Posibil corupt sau extensie gresita"
                )
            #Extragem durata in secunde
            duration=getattr(audio.info,"length",None)
            if duration is None or duration <=0:
                return self._reject(
                    "INVALID_DURATION",
                    f"Durata audio invalida: {duration} secunde"
                )
            # Durata minimă: 5 secunde (mai scurt probabil e un test)
            if duration < 5:
                return self._reject(
                    "TOO_SHORT",
                    f"Înregistrarea e prea scurtă ({duration:.1f}s). Minimum: 5 secunde."
                )
 
            # Durata maximă: 12 ore (o ședință de 12h ar fi excepțională)
            if duration > 43200:
                return self._reject(
                    "TOO_LONG",
                    f"Înregistrarea depășește 12 ore ({duration/3600:.1f}h)."
                )
            
            
            # Extragem sample rate și canale (opționale, nu blocăm dacă lipsesc)
            sample_rate = getattr(audio.info, "sample_rate", None)
            channels = getattr(audio.info, "channels", None)
            bitrate = getattr(audio.info, "bitrate", None)
 
            metadata = AudioMetadata(
                filename=file_path.name,
                file_path=file_path,
                file_size_bytes=file_size,
                file_hash_sha256=file_hash,
                audio_format=extension,
                duration_seconds=int(duration),
                sample_rate_hz=int(sample_rate) if sample_rate else None,
                channels=int(channels) if channels else None,
                bitrate_kbps=int(bitrate / 1000) if bitrate else None,
            )
 
            return ValidationResult(is_valid=True, metadata=metadata)
        except Exception as e:
            logger.warning("metadata_extraction_failed",
                         file=file_path.name, error=str(e))
            return self._reject(
                "METADATA_ERROR",
                f"Eroare la citirea metadatelor audio: {e}"
            )
    @staticmethod
    def _reject(error_code: str, error_message: str) -> ValidationResult:
        """Helper: creeaza un ValidationResult negativ cu logging"""
        logger.warning(
            "validation_failed",
            error_code=error_code,
            error_message=error_message,
        )
        return ValidationResult(
            is_valid=False,
            error_code=error_code,
            error_message=error_message
        )




