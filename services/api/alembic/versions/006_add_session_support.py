"""Add session_id and recording_audio_segments for multi-segment uploads

Revision ID: 006
Revises: 005
Create Date: 2026-03-24
"""
from typing import Sequence, Union
from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE recordings
            ADD COLUMN IF NOT EXISTS session_id UUID
    """)

    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_recordings_session_id
            ON recordings(session_id)
            WHERE session_id IS NOT NULL
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS recording_audio_segments (
            id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            recording_id     UUID NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
            segment_index    INTEGER NOT NULL,
            file_path        VARCHAR(1000) NOT NULL,
            file_hash_sha256 CHAR(64),
            file_size_bytes  BIGINT,
            duration_seconds INTEGER,
            status           VARCHAR(20) NOT NULL DEFAULT 'queued',
            error_message    TEXT,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT unique_audio_segment UNIQUE (recording_id, segment_index)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_audio_segments_recording_id
            ON recording_audio_segments(recording_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_audio_segments_recording_id")
    op.execute("DROP TABLE IF EXISTS recording_audio_segments")
    op.execute("DROP INDEX IF EXISTS idx_recordings_session_id")
    op.execute("ALTER TABLE recordings DROP COLUMN IF EXISTS session_id")
