# services/api/src/models/audit_log.py
import uuid
import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Boolean, Text, TIMESTAMP, Index, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.models.base import Base


class AuditAction(str, enum.Enum):
    CREATE           = "CREATE"
    UPDATE           = "UPDATE"
    UPLOAD           = "UPLOAD"
    VIEW             = "VIEW"
    SEARCH           = "SEARCH"
    EXPORT           = "EXPORT"
    DELETE           = "DELETE"
    TRANSCRIBE       = "TRANSCRIBE"
    LOGIN            = "LOGIN"
    RETENTION_DELETE = "RETENTION_DELETE"
    SEMANTIC_SEARCH  = "SEMANTIC_SEARCH"


class AuditLog(Base):
    """
    Fiecare acțiune importantă în sistem lasă o urmă aici.
    Cerință legală: cine a văzut/exportat ce și când.
    IMPORTANT: AuditLog NU se modifică și NU se șterge devreme.
    """
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    timestamp: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    # Cine
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True   # NULL = request neautentificat
    )
    user_ip: Mapped[str] = mapped_column(INET, nullable=False)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500))

    # Ce acțiune
    action: Mapped[str] = mapped_column(
        SAEnum(AuditAction, name="audit_action", create_type=False), nullable=False
    )
    resource_type: Mapped[Optional[str]] = mapped_column(String(100))
    resource_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )

    # Detalii extra în JSONB (flexibil)
    details: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        Index("idx_audit_timestamp", "timestamp"),
        Index("idx_audit_action",    "action"),
        Index("idx_audit_resource",  "resource_type", "resource_id"),
    )


class User(Base):
    """Utilizatorii sistemului."""
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    last_login: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )