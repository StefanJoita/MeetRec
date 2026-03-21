import math
import uuid
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.middleware.auth import hash_password, verify_password
from src.models.audit_log import User
from src.schemas.user import UserCreate, UserUpdate, PaginatedUsers, UserListItem


class UserConflictError(Exception):
    pass


class UserActionForbiddenError(Exception):
    pass


class UserService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_users(
        self,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
        include_inactive: bool = False,
    ) -> PaginatedUsers:
        query = select(User)

        if not include_inactive:
            query = query.where(User.is_active == True)

        if search:
            term = f"%{search}%"
            query = query.where(
                User.username.ilike(term) | User.email.ilike(term)
            )

        count_query = select(func.count()).select_from(query.subquery())
        total = await self.db.scalar(count_query) or 0

        offset = (page - 1) * page_size
        result = await self.db.execute(
            query.order_by(User.created_at.desc()).offset(offset).limit(page_size)
        )
        users = result.scalars().all()

        return PaginatedUsers(
            items=[
                UserListItem(
                    id=u.id,
                    username=u.username,
                    email=u.email,
                    full_name=u.full_name,
                    is_active=u.is_active,
                    is_admin=u.is_admin,
                    must_change_password=u.must_change_password,
                    last_login=u.last_login,
                    created_at=u.created_at,
                )
                for u in users
            ],
            total=total,
            page=page,
            page_size=page_size,
            pages=math.ceil(total / page_size) if total > 0 else 0,
        )

    async def get_by_id(self, user_id: uuid.UUID) -> Optional[User]:
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def create_user(self, data: UserCreate) -> User:
        user = User(
            username=data.username.strip(),
            email=str(data.email).strip().lower(),
            full_name=data.full_name.strip() if data.full_name else None,
            password_hash=hash_password(data.password),
            is_admin=data.is_admin,
            is_active=True,
            must_change_password=True,
        )
        self.db.add(user)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            raise UserConflictError("Username sau email deja existent.") from exc
        return user

    async def update_user(
        self,
        target_user: User,
        data: UserUpdate,
        actor_user: User,
    ) -> User:
        if target_user.id == actor_user.id:
            if data.is_admin is False:
                raise UserActionForbiddenError(
                    "Nu îți poți revoca singur drepturile de administrator."
                )
            if data.is_active is False:
                raise UserActionForbiddenError(
                    "Nu îți poți dezactiva propriul cont."
                )

        update_data = data.model_dump(exclude_unset=True)
        if "email" in update_data and update_data["email"] is not None:
            update_data["email"] = str(update_data["email"]).strip().lower()

        for field, value in update_data.items():
            setattr(target_user, field, value)

        try:
            await self.db.flush()
        except IntegrityError as exc:
            raise UserConflictError("Username sau email deja existent.") from exc

        return target_user

    async def delete_user(self, target_user: User, actor_user: User) -> None:
        if target_user.id == actor_user.id:
            raise UserActionForbiddenError("Nu îți poți șterge propriul cont.")

        await self.db.delete(target_user)
        await self.db.flush()

    async def change_password_on_first_login(
        self,
        current_user: User,
        current_password: str,
        new_password: str,
    ) -> None:
        if not verify_password(current_password, current_user.password_hash):
            raise UserActionForbiddenError("Parola curentă este incorectă.")

        if current_password == new_password:
            raise UserActionForbiddenError("Noua parolă trebuie să fie diferită de cea curentă.")

        current_user.password_hash = hash_password(new_password)
        current_user.must_change_password = False
        await self.db.flush()
