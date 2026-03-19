# services/api/src/routers/auth.py
# ============================================================
# Auth Router — Login / Logout / Me
# ============================================================

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.middleware.auth import (
    authenticate_user,
    create_access_token,
    get_current_user,
    settings,
)
from src.models.audit_log import User
from src.schemas.recording import LoginRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["autentificare"])


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Autentificare utilizator",
)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Autentifică utilizatorul cu username + parolă.
    Returnează un JWT token valid 8 ore.
    """
    user = await authenticate_user(body.username, body.password, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nume de utilizator sau parolă incorectă.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Actualizăm last_login
    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(last_login=datetime.now(timezone.utc))
    )
    await db.commit()

    token = create_access_token(str(user.id))
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.jwt_expire_minutes * 60,
    )


@router.post(
    "/logout",
    summary="Deconectare utilizator",
)
async def logout(
    current_user: User = Depends(get_current_user),
):
    """
    Deconectează utilizatorul curent.
    JWT e stateless — invalidarea se face pe client (șterge tokenul).
    """
    return {"message": "Deconectat cu succes."}


@router.get(
    "/me",
    summary="Utilizatorul curent autentificat",
)
async def me(
    current_user: User = Depends(get_current_user),
):
    """
    Returnează informațiile utilizatorului autentificat.
    Folosit de frontend la startup pentru a verifica sesiunea.
    """
    return {
        "id": str(current_user.id),
        "username": current_user.username,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "is_admin": current_user.is_admin,
    }
