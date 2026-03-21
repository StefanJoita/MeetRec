#services/ingest/src/logger.py
#=========================================================================
#Logging structurat cu structlog
#=========================================================================
# Logging clasic (greu de căutat):
#   "[2024-01-15 10:23:41] ERROR ingest: Fișier invalid sedinta.mp3"
#
# Logging structurat JSON — ușor de filtrat cu docker compose logs:
#   {
#     "timestamp": "2024-01-15T10:23:41Z",
#     "level": "error",
#     "service": "ingest",
#     "event": "file_invalid",
#     "filename": "sedinta.mp3",
#     "reason": "format_not_supported",
#     "format_detected": "pdf"
#   }
# ==============================================================================
import logging
import structlog
from src.config import settings

def setup_logging()->None:
    """Configurează structlog pentru logging structurat pentru intreg serviciul."""
    #nivelul de logging este configurat din settings
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    #Configuram structLog cu o serie de processors
    #fiecare processor transforma log entry-ul inainte sa fie scris
    structlog.configure(
        processors=[
            #1. Adauga timestamp in format ISO8601
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            #2. Adauga stack trace la exceptii  
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            #3. Output : json in productie, text colorat in dev
            structlog.processors.JSONRenderer()
            if settings.log_level != "DEBUG"
            else structlog.dev.ConsoleRenderer(colors=True)
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    #Configuram si logging-ul standard Python (pentru librarii third-party)
    logging.basicConfig(
        format="%(message)s",
        level=log_level,
    )

def get_logger(name: str) -> structlog.BoundLogger:
    """
    Returnează un logger cu contextul serviciului pre-setat.
    
    Folosire:
        logger = get_logger(__name__)
        logger.info("file_detected", filename="sedinta.mp3", size_mb=45.2)
    """
    return structlog.get_logger(name).bind(service="ingest")