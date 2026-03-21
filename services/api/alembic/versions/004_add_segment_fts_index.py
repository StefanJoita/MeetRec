"""GIN Index pentru full-text search pe transcript_segments

Revision ID: 004
Revises: 003
Create Date: 2026-03-21

Motivație: to_tsvector() se calcula ON THE FLY la fiecare căutare — full table scan.
Soluție: coloană TSVECTOR generată automat + GIN index pentru Index Scan.
"""
from typing import Sequence, Union
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Adaugă coloana search_vector generată automat
    op.execute("""
        ALTER TABLE transcript_segments
        ADD COLUMN IF NOT EXISTS search_vector TSVECTOR
            GENERATED ALWAYS AS (to_tsvector('romanian', coalesce(text, ''))) STORED
    """)

    # Creează GIN index (CONCURRENTLY nu merge în tranzacție, dar merge în Alembic cu autocommit)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_transcript_segments_search_vector
        ON transcript_segments USING GIN (search_vector)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_transcript_segments_search_vector")
    op.execute("ALTER TABLE transcript_segments DROP COLUMN IF EXISTS search_vector")
