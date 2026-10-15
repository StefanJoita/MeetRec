"""Add transcripts.*_sec: durata etapelor transcrierii (Administrare → Procesări)

Revision ID: 011
Revises: 010
Create Date: 2026-10-14
"""
from typing import Sequence, Union
from alembic import op

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE transcripts
            ADD COLUMN IF NOT EXISTS transcription_sec    NUMERIC(8,1),
            ADD COLUMN IF NOT EXISTS alignment_sec        NUMERIC(8,1),
            ADD COLUMN IF NOT EXISTS diarization_sec      NUMERIC(8,1),
            ADD COLUMN IF NOT EXISTS diarization_parallel BOOLEAN NOT NULL DEFAULT FALSE
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE transcripts
            DROP COLUMN IF EXISTS transcription_sec,
            DROP COLUMN IF EXISTS alignment_sec,
            DROP COLUMN IF EXISTS diarization_sec,
            DROP COLUMN IF EXISTS diarization_parallel
    """)
