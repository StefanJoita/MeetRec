"""Add speaker_mapping to recordings for diarization speaker assignment

Revision ID: 008
Revises: 007
Create Date: 2026-03-27
"""
from typing import Sequence, Union
from alembic import op

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE recordings
            ADD COLUMN IF NOT EXISTS speaker_mapping JSONB DEFAULT '{}'
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE recordings DROP COLUMN IF EXISTS speaker_mapping")
