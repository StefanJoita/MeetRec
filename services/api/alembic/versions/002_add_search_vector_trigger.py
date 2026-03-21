"""Trigger pentru actualizarea search_vector în transcrieri

Revision ID: 002
Revises: 001
Create Date: 2026-03-19

Motivație: trigger-ul din init.sql nu a fost creat pe DB-ul existent.
Fără acest trigger, căutarea full-text nu funcționează pentru înregistrările noi.
"""
from typing import Sequence, Union
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION fn_update_search_vector()
        RETURNS TRIGGER AS $$
        BEGIN
            UPDATE transcripts
            SET search_vector = (
                SELECT to_tsvector('romanian', string_agg(text, ' '))
                FROM transcript_segments
                WHERE transcript_id = NEW.transcript_id
            )
            WHERE id = NEW.transcript_id;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        DROP TRIGGER IF EXISTS update_search_vector_on_segment ON transcript_segments;
        CREATE TRIGGER update_search_vector_on_segment
            AFTER INSERT ON transcript_segments
            FOR EACH ROW EXECUTE FUNCTION fn_update_search_vector();
    """)

    # Backfill: populează search_vector pentru transcriptele completate existente
    op.execute("""
        UPDATE transcripts t
        SET search_vector = (
            SELECT to_tsvector('romanian', string_agg(seg.text, ' '))
            FROM transcript_segments seg
            WHERE seg.transcript_id = t.id
        )
        WHERE t.status = 'completed'
          AND t.search_vector IS NULL;
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS update_search_vector_on_segment ON transcript_segments")
    op.execute("DROP FUNCTION IF EXISTS fn_update_search_vector()")
