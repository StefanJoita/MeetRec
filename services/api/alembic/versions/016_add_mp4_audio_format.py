"""Adaugă valoarea 'mp4' în enum audio_format

Fișierele MP4 sunt acceptate la încărcare (doar audio sau cu video — se transcrie sunetul).

Revision ID: 016
Revises: 015
Create Date: 2026-10-29
"""
from typing import Sequence, Union
from alembic import op

revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE audio_format ADD VALUE IF NOT EXISTS 'mp4'")


def downgrade() -> None:
    # PostgreSQL nu permite ștergerea valorilor dintr-un enum — downgrade nu face nimic.
    pass
