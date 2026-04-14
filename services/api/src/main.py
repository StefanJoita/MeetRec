# services/api/src/main.py
# ============================================================
# FastAPI Application — Entry Point
# ============================================================

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
import structlog

from src.config import settings
from src.routers import recordings, transcript, search, auth, export, audit, inbox, users

logger = structlog.get_logger()

# ── Rate Limiter ─────────────────────────────────────────────
# Folosit de endpoint-urile cu @limiter.limit() pentru protecție brute-force
limiter = Limiter(key_func=get_remote_address)


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
# Exportăm limiter-ul pentru a fi importat de routers
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
    # Previne 307 redirect când ruta e apelată fără trailing slash
    # (ex: /api/v1/recordings → /api/v1/recordings/ via Location: http://internal-host/...)
    redirect_slashes=False,
)

# Atașăm limiter-ul la app state și handler-ul de 429
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Middleware: Must-Change-Password Check ───────────────────
# Verifică dacă utilizatorul trebuie să-și schimbe parola la primul login
@app.middleware("http")
async def check_must_change_password(request: Request, call_next):
    p = request.url.path

    exempt_paths = {"/health", "/docs", "/openapi.json", "/redoc"}
    if p in exempt_paths:
        return await call_next(request)

    # Căile care nu necesită schimbarea parolei (cu prefix /api/v1)
    change_password_exempt = {
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
        "/api/v1/auth/change-password-first-login",
    }
    if p in change_password_exempt:
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        from src.middleware.auth import decode_token
        from src.database import session_factory
        from src.models.audit_log import User
        from sqlalchemy import select
        token = auth_header[7:]
        user_id = decode_token(token)
        if user_id:
            async with session_factory() as db:
                result = await db.execute(
                    select(User).where(User.id == user_id, User.is_active == True)
                )
                user = result.scalar_one_or_none()
                if user and user.must_change_password:
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "Trebuie să-ți schimbi parola la primul login. Utilizează /auth/change-password-first-login"}
                    )

    return await call_next(request)


# ── Middleware ───────────────────────────────────────────────
# CORS = Cross-Origin Resource Sharing
# Permite browser-ului să facă request-uri din alt domeniu
# În producție: restrânge la domeniul real!
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.app_env == "development" else settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# ── Routers ──────────────────────────────────────────────────
# prefix="/api/v1" = toate endpoint-urile vor fi la /api/v1/recordings etc.
# Versioning (/v1/) = în viitor poți adăuga /v2/ fără să strici /v1/
app.include_router(auth.router, prefix="/api/v1")
app.include_router(inbox.router, prefix="/api/v1")
app.include_router(recordings.router, prefix="/api/v1")
app.include_router(transcript.router, prefix="/api/v1")
app.include_router(search.router, prefix="/api/v1")
app.include_router(export.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")

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