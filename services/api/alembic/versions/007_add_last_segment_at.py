"""Add last_segment_at to recordings for session assembly timeout

Revision ID: 007
Revises: 006
Create Date: 2026-03-24
"""
from typing import Sequence, Union
from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE recordings
            ADD COLUMN IF NOT EXISTS last_segment_at TIMESTAMPTZ
    """)

    # Index parțial — conține doar sesiunile active (session_id IS NOT NULL AND status='queued')
    # Watcher-ul caută exclusiv în această mulțime → index mic, query rapid
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_recordings_session_watcher
            ON recordings (last_segment_at)
            WHERE session_id IS NOT NULL AND status = 'queued'
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_recordings_session_watcher")
    op.execute("ALTER TABLE recordings DROP COLUMN IF EXISTS last_segment_at")
