"""Add session_registered to recording_status enum

Revision ID: 009
Revises: 008
Create Date: 2026-04-02
"""
from typing import Sequence, Union
from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE recording_status ADD VALUE IF NOT EXISTS 'session_registered'")


def downgrade() -> None:
    # PostgreSQL nu permite ștergerea valorilor dintr-un enum — downgrade nu face nimic.
    # Pentru a reveni complet, șterge manual înregistrările cu acest status
    # și recreează enum-ul fără valoarea 'session_registered'.
    pass
