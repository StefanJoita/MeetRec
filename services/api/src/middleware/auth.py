# services/api/src/middleware/auth.py
# ============================================================
# Autentificare JWT — protejează endpoint-urile API
# ============================================================
# JWT (JSON Web Token) 101:
#
# 1. Utilizatorul trimite: POST /auth/login {username, password}
# 2. API-ul verifică parola (bcrypt), generează un token:
#    {"sub": "user_id", "exp": timestamp} + semnătură HS256
# 3. Clientul salvează tokenul și îl trimite la fiecare request:
#    Authorization: Bearer eyJhbGci...
# 4. API-ul verifică semnătura + expirarea → știe cine e userul
#
# De ce JWT și nu sesiuni server-side?
# - Stateless: serverul nu stochează sesiuni
# - Scalabil: orice instanță API poate verifica tokenul
# - Offline: nu trebuie DB la fiecare request
# ============================================================

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import get_db
from src.models.audit_log import User

# ── Password Hashing ─────────────────────────────────────────
# bcrypt = algoritm lent intenționat (protecție brute force)
# "deprecated=auto" = actualizează automat hash-urile vechi
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ── JWT Bearer ───────────────────────────────────────────────
# HTTPBearer extrage automat tokenul din header-ul Authorization
bearer_scheme = HTTPBearer(auto_error=False)


# ── Funcții helper pentru parole ─────────────────────────────

def hash_password(password: str) -> str:
    """Generează hash bcrypt dintr-o parolă în clar."""
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Verifică dacă parola în clar corespunde hash-ului stocat."""
    return pwd_context.verify(plain, hashed)


# ── Funcții pentru JWT ────────────────────────────────────────

def create_access_token(user_id: str) -> str:
    """
    Generează un JWT token pentru utilizatorul dat.

    Token-ul conține:
    - sub: ID-ul utilizatorului (subject)
    - exp: data expirării (în UTC)
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": user_id,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> Optional[str]:
    """
    Decodează și validează un JWT token.

    Returns:
        user_id dacă tokenul e valid, None dacă e expirat/invalid.
    """
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
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Dependency FastAPI: extrage utilizatorul curent din token JWT.
    Adaugă la orice endpoint cu: current_user: User = Depends(get_current_user)

    Ridică 401 dacă:
    - Tokenul lipsește
    - Tokenul e invalid sau expirat
    - Utilizatorul nu mai există în DB
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Autentificare necesară.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not credentials:
        raise unauthorized

    user_id = decode_token(credentials.credentials)
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
    """
    Dependency: verifică că utilizatorul curent este admin.
    Adaugă la endpoint-uri administrative.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acces interzis. Necesită drepturi de administrator.",
        )
    return current_user


# ── Auth Router helper ────────────────────────────────────────

async def authenticate_user(
    username: str,
    password: str,
    db: AsyncSession,
) -> Optional[User]:
    """
    Verifică credențialele și returnează utilizatorul dacă sunt corecte.
    Folosit în POST /auth/login.
    """
    result = await db.execute(
        select(User).where(User.username == username, User.is_active == True)
    )
    user = result.scalar_one_or_none()
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
