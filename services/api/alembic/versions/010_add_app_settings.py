"""Add app_settings: setări de funcționare schimbate din interfața de administrare

Revision ID: 010
Revises: 009
Create Date: 2026-10-14
"""
from typing import Sequence, Union
from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key         VARCHAR(100) PRIMARY KEY,
            value       JSONB NOT NULL,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_by  UUID REFERENCES users(id) ON DELETE SET NULL
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app_settings")
