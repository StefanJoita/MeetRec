# services/api/src/main.py
# ============================================================
# FastAPI Application — Entry Point
# ============================================================

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog

from src.config import settings
from src.routers import recordings, transcript, search, auth, export, audit

logger = structlog.get_logger()


# ── Lifecycle ────────────────────────────────────────────────
# @asynccontextmanager lifespan = cod rulat la startup și shutdown
# Înlocuiește @app.on_event("startup") care e deprecated în FastAPI modern
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── STARTUP ──────────────────────────────────────────────
    logger.info("api_starting", env=settings.app_env, port=settings.api_port)
    # Aici am conecta la DB, am verifica Redis, etc.
    yield
    # ── SHUTDOWN ─────────────────────────────────────────────
    logger.info("api_stopping")


# ── Aplicația FastAPI ────────────────────────────────────────
app = FastAPI(
    title="Meeting Transcriber API",
    description="""
    API pentru gestionarea și transcrierea înregistrărilor audio ale ședințelor.

    ## Funcționalități
    - 📥 **Înregistrări**: CRUD complet pentru înregistrări audio
    - 🎙️ **Transcrieri**: Acces la transcripturi cu timestamps
    - 🔍 **Căutare**: Full-text search în toate transcripturile
    - 📤 **Export**: PDF, DOCX, TXT
    - 📋 **Audit**: Log complet al acceselor și acțiunilor
    """,
    version="1.0.0",
    lifespan=lifespan,
    # În producție, dezactivăm /docs pentru securitate:
    docs_url="/docs" if settings.app_env == "development" else None,
    redoc_url="/redoc" if settings.app_env == "development" else None,
)

# ── Middleware ───────────────────────────────────────────────
# CORS = Cross-Origin Resource Sharing
# Permite browser-ului să facă request-uri din alt domeniu
# În producție: restrânge la domeniul real!
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.app_env == "development" else [
        "https://meeting-transcriber.local"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────
# prefix="/api/v1" = toate endpoint-urile vor fi la /api/v1/recordings etc.
# Versioning (/v1/) = în viitor poți adăuga /v2/ fără să strici /v1/
app.include_router(auth.router, prefix="/api/v1")
app.include_router(recordings.router, prefix="/api/v1")
app.include_router(transcript.router, prefix="/api/v1")
app.include_router(search.router, prefix="/api/v1")
app.include_router(export.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")

# ── Health Check ─────────────────────────────────────────────
@app.get("/health", tags=["system"])
async def health_check():
    """
    Verifică că API-ul funcționează.
    Folosit de Docker healthcheck și de load balancer.
    Returnează 200 OK dacă totul e ok.
    """
    return {
        "status": "healthy",
        "service": "meeting-transcriber-api",
        "version": "1.0.0",
        "environment": settings.app_env,
    }

# ── Global Exception Handler ─────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Prinde orice excepție neașteptată și returnează 500 cu mesaj clar.
    Fără asta: utilizatorul vede un stack trace Python (informații sensibile!).
    Cu asta: utilizatorul vede {"detail": "Eroare internă"} — sigur.
    """
    logger.error("unhandled_exception",
                 path=request.url.path,
                 method=request.method,
                 error=str(exc))
    return JSONResponse(
        status_code=500,
        content={"detail": "Eroare internă a serverului. Administratorul a fost notificat."}
    )