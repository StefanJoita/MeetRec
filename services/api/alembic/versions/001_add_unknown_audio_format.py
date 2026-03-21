"""Adaugă valoarea 'unknown' în enum audio_format

Revision ID: 001
Revises:
Create Date: 2026-03-19

Motivație: înregistrările create prin API (fără fișier audio) au nevoie
de un format placeholder până când fișierul este uploadat.
"""
from typing import Sequence, Union
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE audio_format ADD VALUE IF NOT EXISTS 'unknown'")


def downgrade() -> None:
    # PostgreSQL nu permite ștergerea valorilor dintr-un ENUM fără recrearea tipului
    # Downgrade-ul nu este implementat — înregistrările cu format 'unknown' ar rămâne orfane
    pass
