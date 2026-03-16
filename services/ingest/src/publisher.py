#services/ingest/src/publisher.py
#===== ================================================================
# Publisher — Publică mesaje în Redis Queue
#=================================================================
#
#Pattern : Producer-Consumer cu Redis List
#
# Ingest (Producer)         Redis List              STT Worker (Consumer)
#      │                  ┌──────────┐                      │
#      │──── LPUSH ──────▶│ job_5    │                      │
#      │                  │ job_4    │                      │
#      │                  │ job_3    │◀──── BRPOP ──────────│
#      │                  │ job_2    │   (blochează până     │
#      │                  │ job_1    │    apare un job)      │
#      │                  └──────────┘                      │
#
# LPUSH = adaugă la stânga (capul listei) → cel mai nou
# BRPOP = ia de la dreapta (coada listei) → cel mai vechi (FIFO)
# FIFO = First In, First Out (primul intrat, primul procesat)
# ============================================================
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import redis
from tenacity import retry,stop_after_attempt, wait_exponential
from src.config import settings
from src.logger import get_logger   
from src.validator import AudioMetadata

logger=get_logger(__name__)

class TranscriptionJob: 
    """
    Structura unui job de transcriere.
    Aceasta e 'comanda' trimisa la STT Worker.
    """
    def __init__(
            self,
            recording_id:str,
            file_path:str,
            audio_format:str,
            duration_seconds:int,
            language_hint:str="ro", #ajutor pentru Whisper
            priority: int=0, #0 = normal, 1 = urgent
            
    ):
        self.recording_id=recording_id
        self.file_path=file_path
        self.audio_format=audio_format 
        self.duration_seconds=duration_seconds
        self.language_hint=language_hint
        self.priority=priority
        self.created_at=datetime.now(timezone.utc).isoformat()
        #estimare timp de procesare (ajuta la planificare)
        #regula empirica: 1 minut audio = 1-3 minute procesare CPU cu whisper medium
        self.estimated_processing_time_minutes= max(1, duration_seconds // 30)
    
    def to_dict(self):
        "Convertim la dict pentru serializare JSON"
        return {
            "recording_id": self.recording_id,
            "file_path": self.file_path,
            "audio_format": self.audio_format,
            "duration_seconds": self.duration_seconds,
            "language_hint": self.language_hint,
            "priority": self.priority,
            "created_at": self.created_at,
            "estimated_processing_time_minutes": self.estimated_processing_time_minutes
        }  
    
    def to_json(self):
        "Serializam la JSON pentru a trimite in Redis"
        return json.dumps(self.to_dict(), ensure_ascii=False)
        #ensure_ascii=False pentru a păstra caracterele UTF-8 (ex: diacritice)


class JobPublisher:
    """
    Publică joburi de transcriere în Redis Queue.
    """
    def __init__(self):
        self._redis:Optional[redis.Redis]=None
    
    def _get_redis(self) -> redis.Redis:
        """
        Conexiune lazy la Redis(se conecteaza doar la primul ape)
        Lasy= nu ne conectam la startup ci cand avem nevoie
        Avantaj: daca redis e momentan indisponibil la startup, serviciul tot porneste
        """
        if self._redis is None:
            self._redis=redis.from_url(
                settings.redis_url,
                decode_responses=True, #pentru a primi stringuri in loc de bytes
                socket_timeout=5, #timeout pentru operatiuni redis
                socket_connect_timeout=5 #timeout pentru conexiune
            )
        return self._redis
    #@retry = incearca din nou automat daca esueaza
    #stop_after_attempt(3) = incearca de maxim 3 ori
    #wait_exponential(multiplier=1, min=1, max=10) = asteapta un timp exponential intre incercari (1s, 2s, 4s, etc)
    #de ce backopff exponential? pentru a evita sa suprasolicitam redis daca e deja sub presiune
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=
1, min=1, max=10))
    def publish_transcription_job(
        self,
        recording_id:str,
        metadata:AudioMetadata,
        stored_path:Path,
        )->bool:
            """Publica un job de transcriere in Redis.
            Args:
                recording_id: ID unic pentru inregistrare (UUID)
                metadata: Metadata extrasa de validator
                stored_path: Calea unde fisierul a fost stocat in storage organizat 
            Return:
                True daca jobul a fost publicat cu succes, False altfel
            """
            job=TranscriptionJob(
                recording_id=recording_id,
                file_path=str(stored_path),
                audio_format=metadata.audio_format,
                duration_seconds=metadata.duration_seconds,
                language_hint="ro"
            )  
            try:
                r=self._get_redis()
                #LPUSH adauga la stanga (capul listei) pentru a avea FIFO
                queue_length=r.lpush(
                    settings.redis_transcription_queue,
                    job.to_json()
                )
                logger.info(
                    "job_published",
                    recording_id=recording_id,
                    queue=settings.redis_transcription_queue,
                    queue_length=queue_length, #cate joburi sunt acum in coada
                    estimated_processing_time_minutes=job.estimated_processing_time_minutes
                )
                return True
            except redis.RedisError as e:
                logger.error(
                    "redis_publish_failed",
                    recording_id=recording_id,
                    error=str(e)
                )
                raise #re-raise pentru a fi prins de retry si a incerca din nou

    def get_queue_length(self) -> int:
        """Returneaza numarul de joburi in coada de transcriere."""
        return self._get_redis().llen(settings.redis_transcription_queue)   

    def health_check(self) -> bool:
        """Verifica daca conexiunea la Redis este sanatoasa."""
        try:
            r=self._get_redis()
            r.ping() #ping pentru a verifica conexiunea
            return True
        except redis.RedisError as e:
            logger.error("redis_health_check_failed", error=str(e))
            return False