import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.middleware.audit import log_audit
from src.middleware.auth import get_current_admin
from src.models.audit_log import User
from src.schemas.user import PaginatedUsers, UserResponse, UserCreate, UserUpdate
from src.services.user_service import UserService, UserConflictError, UserActionForbiddenError


router = APIRouter(prefix="/users", tags=["users"])


def get_user_service(db: AsyncSession = Depends(get_db)) -> UserService:
    return UserService(db)


@router.get("", response_model=PaginatedUsers, summary="Listează utilizatorii")
async def list_users(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(default=None),
    include_inactive: bool = Query(default=False),
    _: User = Depends(get_current_admin),
    service: UserService = Depends(get_user_service),
    db: AsyncSession = Depends(get_db),
):
    result = await service.list_users(
        page=page,
        page_size=page_size,
        search=search,
        include_inactive=include_inactive,
    )
    await log_audit(request, db, action="VIEW", resource_type="users_list")
    return result


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED, summary="Creează utilizator")
async def create_user(
    data: UserCreate,
    request: Request,
    _: User = Depends(get_current_admin),
    service: UserService = Depends(get_user_service),
    db: AsyncSession = Depends(get_db),
):
    try:
        user = await service.create_user(data)
    except UserConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await log_audit(request, db, action="CREATE", resource_type="user", resource_id=user.id)
    return user


@router.get("/{user_id}", response_model=UserResponse, summary="Detalii utilizator")
async def get_user(
    user_id: uuid.UUID,
    _: User = Depends(get_current_admin),
    service: UserService = Depends(get_user_service),
):
    user = await service.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Utilizatorul nu există.")
    return user


@router.patch("/{user_id}", response_model=UserResponse, summary="Actualizează utilizator")
async def update_user(
    user_id: uuid.UUID,
    data: UserUpdate,
    request: Request,
    current_admin: User = Depends(get_current_admin),
    service: UserService = Depends(get_user_service),
    db: AsyncSession = Depends(get_db),
):
    target_user = await service.get_by_id(user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="Utilizatorul nu există.")

    try:
        updated = await service.update_user(target_user, data, actor_user=current_admin)
    except UserActionForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except UserConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await log_audit(request, db, action="UPDATE", resource_type="user", resource_id=updated.id)
    return updated


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Șterge definitiv utilizator")
async def delete_user(
    user_id: uuid.UUID,
    request: Request,
    current_admin: User = Depends(get_current_admin),
    service: UserService = Depends(get_user_service),
    db: AsyncSession = Depends(get_db),
):
    target_user = await service.get_by_id(user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="Utilizatorul nu există.")

    try:
        await service.delete_user(target_user, actor_user=current_admin)
    except UserActionForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    await log_audit(request, db, action="DELETE", resource_type="user", resource_id=target_user.id)
