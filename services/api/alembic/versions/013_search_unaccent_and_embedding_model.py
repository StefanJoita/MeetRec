"""Căutare: full-text insensibil la diacritice, modelul embedding-ului, fără search_vector pe transcripts

- configurația romanian_unaccent („sedinta” găsește „ședința”, și invers)
- transcript_segments.search_vector regenerat cu romanian_unaccent
- transcript_segments.embedding_model: vectorii de la alt model / alte setări se recalculează
- transcripts.search_vector + trigger-ul care îl reconstruia la FIECARE segment inserat
  (agregare pe toată transcrierea, pentru fiecare rând) eliminate: nu mai sunt folosite

Revision ID: 013
Revises: 012
Create Date: 2026-10-15
"""
from typing import Sequence, Union
from alembic import op

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = 'romanian_unaccent') THEN
                CREATE TEXT SEARCH CONFIGURATION romanian_unaccent (COPY = romanian);
                ALTER TEXT SEARCH CONFIGURATION romanian_unaccent
                    ALTER MAPPING FOR word, hword, hword_part, asciiword, asciihword, hword_asciipart
                    WITH unaccent, romanian_stem;
            END IF;
        END $$
    """)

    # Expresia unei coloane generate nu se poate schimba în PG15: o recreăm
    op.execute("DROP INDEX IF EXISTS idx_transcript_segments_search_vector")
    op.execute("ALTER TABLE transcript_segments DROP COLUMN IF EXISTS search_vector")
    op.execute("""
        ALTER TABLE transcript_segments
        ADD COLUMN search_vector TSVECTOR
            GENERATED ALWAYS AS (to_tsvector('romanian_unaccent', coalesce(text, ''))) STORED
    """)
    op.execute("""
        CREATE INDEX idx_transcript_segments_search_vector
        ON transcript_segments USING GIN (search_vector)
    """)

    op.execute("ALTER TABLE transcript_segments ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(150)")

    op.execute("DROP TRIGGER IF EXISTS update_search_vector_on_segment ON transcript_segments")
    op.execute("DROP FUNCTION IF EXISTS fn_update_search_vector()")
    op.execute("DROP INDEX IF EXISTS idx_transcripts_search")
    op.execute("ALTER TABLE transcripts DROP COLUMN IF EXISTS search_vector")


def downgrade() -> None:
    op.execute("ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS search_vector TSVECTOR")
    op.execute("ALTER TABLE transcript_segments DROP COLUMN IF EXISTS embedding_model")
    op.execute("DROP INDEX IF EXISTS idx_transcript_segments_search_vector")
    op.execute("ALTER TABLE transcript_segments DROP COLUMN IF EXISTS search_vector")
    op.execute("""
        ALTER TABLE transcript_segments
        ADD COLUMN search_vector TSVECTOR
            GENERATED ALWAYS AS (to_tsvector('romanian', coalesce(text, ''))) STORED
    """)
    op.execute("""
        CREATE INDEX idx_transcript_segments_search_vector
        ON transcript_segments USING GIN (search_vector)
    """)
    op.execute("DROP TEXT SEARCH CONFIGURATION IF EXISTS romanian_unaccent")
