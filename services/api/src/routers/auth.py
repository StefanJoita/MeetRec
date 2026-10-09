# services/api/src/routers/auth.py
# ============================================================
# Auth Router — Login / Logout / Me
# ============================================================

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.limiter import limiter
from src.middleware.audit import log_audit
from src.middleware.auth import (
    authenticate_user,
    create_access_token,
    get_current_user,
    settings,
)
from src.models.audit_log import User
from src.schemas.recording import LoginRequest, TokenResponse
from src.schemas.user import FirstLoginPasswordChangeRequest
from src.services.login_lockout import (
    LOCKOUT_SECONDS,
    MAX_FAILED_ATTEMPTS,
    LoginLockout,
    get_login_lockout,
)
from src.services.user_service import UserService, UserActionForbiddenError

router = APIRouter(prefix="/auth", tags=["autentificare"])


def _invalid_credentials() -> HTTPException:
    # Același răspuns pentru parolă greșită, user inexistent și cont blocat:
    # nu dezvăluim dacă username-ul există sau dacă a fost blocat.
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Nume de utilizator sau parolă incorectă.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _audit_lockout(request: Request, db: AsyncSession, username: str, event: str) -> None:
    await log_audit(
        request, db,
        action="LOGIN",
        resource_type="user",
        details={
            "event": event,
            "username": username,
            "max_failed_attempts": MAX_FAILED_ATTEMPTS,
            "lockout_minutes": LOCKOUT_SECONDS // 60,
        },
        success=False,
    )
    # Commit explicit: răspunsul e 401 (excepție) → get_db() ar face rollback
    await db.commit()


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Autentificare utilizator",
)
@limiter.limit("5/minute")
async def login(
    request: Request,
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
    lockout: LoginLockout = Depends(get_login_lockout),
):
    """
    Autentifică utilizatorul cu username + parolă.
    Returnează un JWT token valid 8 ore.

    Limite: 5/minut per IP și blocarea username-ului 15 minute după
    5 eșecuri consecutive (src/services/login_lockout.py).
    """
    if await lockout.is_locked(body.username):
        await _audit_lockout(request, db, body.username, event="login_rejected_locked")
        raise _invalid_credentials()

    user = await authenticate_user(body.username, body.password, db)
    if not user:
        if await lockout.register_failure(body.username):
            await _audit_lockout(request, db, body.username, event="account_locked")
        raise _invalid_credentials()

    await lockout.reset(body.username)

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
        "is_active": current_user.is_active,
        "is_admin": current_user.is_admin,
        "is_participant": current_user.is_participant,
        "role": current_user.role,
        "must_change_password": current_user.must_change_password,
    }


@router.post(
    "/change-password-first-login",
    summary="Schimbă parola obligatorie la primul login",
)
async def change_password_first_login(
    body: FirstLoginPasswordChangeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = UserService(db)
    try:
        await service.change_password_on_first_login(
            current_user=current_user,
            current_password=body.current_password,
            new_password=body.new_password,
        )
    except UserActionForbiddenError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"message": "Parola a fost schimbată cu succes."}
