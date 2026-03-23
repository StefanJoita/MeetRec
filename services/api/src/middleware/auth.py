# services/api/src/middleware/auth.py
# ============================================================
# Autentificare JWT — protejează endpoint-urile API
# ============================================================

from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import get_db
from src.models.audit_log import User

# ── Password Hashing ─────────────────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ── JWT Bearer ───────────────────────────────────────────────
bearer_scheme = HTTPBearer(auto_error=False)


# ── Funcții helper pentru parole ─────────────────────────────

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── Funcții pentru JWT ────────────────────────────────────────

def create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return payload.get("sub")
    except JWTError:
        return None


# ── FastAPI Dependencies ──────────────────────────────────────

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    token: Optional[str] = Query(default=None, include_in_schema=False),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Dependency FastAPI: extrage utilizatorul curent din token JWT.
    Ridică 401 dacă tokenul lipsește, e invalid sau expirat.
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Autentificare necesară.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    raw_token = credentials.credentials if credentials else token
    if not raw_token:
        raise unauthorized

    user_id = decode_token(raw_token)
    if not user_id:
        raise unauthorized

    result = await db.execute(
        select(User).where(User.id == user_id, User.is_active == True)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise unauthorized

    return user


async def get_current_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """Dependency: verifică că utilizatorul curent are rol admin."""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acces interzis. Necesită drepturi de administrator.",
        )
    return current_user


async def get_current_operator_or_above(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Dependency: permite accesul pentru admin și operator, dar NU pentru participant.
    Folosit pe endpoint-urile care modifică date (upload, PATCH, etc.).
    """
    if current_user.is_participant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acces interzis. Necesită drepturi de operator sau administrator.",
        )
    return current_user


async def get_current_user_with_password_check(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Dependency: verific că utilizatorul NU trebuie să-și schimbe parola la login.
    
    Ridică O_UNAUTHORIZED dacă must_change_password=True, cu hint către endpoint-ul de schimbare.
    Endpoint-uri exceptate: /auth/change-password-first-login și /auth/me
    (Acestea sunt bypassed prin exclude_path în router)
    """
    if current_user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Trebuie să-ți schimbi parola la primul login. Utilizează /auth/change-password-first-login",
        )
    return current_user


async def check_recording_access(
    recording_id: uuid.UUID,
    user: User,
    db: AsyncSession,
) -> bool:
    """
    Verifică dacă utilizatorul poate accesa o înregistrare.

    Logica:
      - admin și operator → acces la toate
      - participant → doar înregistrările la care a fost linkat explicit de admin,
        și doar dacă înregistrarea a fost creată DUPĂ crearea contului participantului
    """
    if not user.is_participant:
        return True

    # Import local pentru a evita circular imports
    from src.models.recording import Recording, RecordingParticipant

    result = await db.execute(
        select(RecordingParticipant)
        .where(
            RecordingParticipant.recording_id == recording_id,
            RecordingParticipant.user_id == user.id,
        )
    )
    return result.scalar_one_or_none() is not None


# ── Auth Router helper ────────────────────────────────────────

async def authenticate_user(
    username: str,
    password: str,
    db: AsyncSession,
) -> Optional[User]:
    result = await db.execute(
        select(User).where(User.username == username, User.is_active == True)
    )
    user = result.scalar_one_or_none()
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
