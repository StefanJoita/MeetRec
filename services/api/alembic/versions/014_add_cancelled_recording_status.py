"""Add cancelled to recording_status enum

Transcrierea poate fi anulată din Administrare → Coadă; înregistrarea rămâne,
cu status 'cancelled', și poate fi repornită cu „Reîncearcă”.

Revision ID: 014
Revises: 013
Create Date: 2026-10-16
"""
from typing import Sequence, Union
from alembic import op

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE recording_status ADD VALUE IF NOT EXISTS 'cancelled'")


def downgrade() -> None:
    # PostgreSQL nu permite ștergerea valorilor dintr-un enum — downgrade nu face nimic.
    # Pentru a reveni complet, mută înregistrările 'cancelled' pe alt status
    # și recreează enum-ul fără această valoare.
    pass
