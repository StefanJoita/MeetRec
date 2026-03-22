import uuid
from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.models.audit_log import UserRole


class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    email: str
    full_name: Optional[str]
    is_active: bool
    is_admin: bool          # proprietate derivată din role
    role: str               # 'admin' | 'operator' | 'participant'
    must_change_password: bool
    created_at: datetime
    last_login: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class UserListItem(BaseModel):
    id: uuid.UUID
    username: str
    email: str
    full_name: Optional[str]
    is_active: bool
    is_admin: bool
    role: str
    must_change_password: bool
    last_login: Optional[datetime]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserSuggest(BaseModel):
    """Răspuns compact pentru autocomplete (Ctrl+K). Admin-only."""
    id: uuid.UUID
    username: str
    full_name: Optional[str]
    email: str
    role: str

    model_config = ConfigDict(from_attributes=True)


class PaginatedUsers(BaseModel):
    items: List[UserListItem]
    total: int
    page: int
    page_size: int
    pages: int


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    email: str = Field(min_length=5, max_length=255)
    full_name: Optional[str] = Field(default=None, max_length=255)
    password: str = Field(min_length=8, max_length=255)
    role: str = UserRole.OPERATOR.value

    @field_validator('email')
    @classmethod
    def validate_email(cls, value: str) -> str:
        if '@' not in value:
            raise ValueError('Email invalid.')
        return value

    @field_validator('role')
    @classmethod
    def validate_role(cls, value: str) -> str:
        allowed = {r.value for r in UserRole}
        if value not in allowed:
            raise ValueError(f'Rol invalid. Valori permise: {allowed}')
        return value


class UserUpdate(BaseModel):
    email: Optional[str] = Field(default=None, min_length=5, max_length=255)
    full_name: Optional[str] = Field(default=None, max_length=255)
    is_active: Optional[bool] = None
    role: Optional[str] = None

    @field_validator('email')
    @classmethod
    def validate_email(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if '@' not in value:
            raise ValueError('Email invalid.')
        return value

    @field_validator('role')
    @classmethod
    def validate_role(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        allowed = {r.value for r in UserRole}
        if value not in allowed:
            raise ValueError(f'Rol invalid. Valori permise: {allowed}')
        return value


class FirstLoginPasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=255)
