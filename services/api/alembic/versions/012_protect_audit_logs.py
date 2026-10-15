"""Protect audit_logs: jurnalul se poate doar completa (UPDATE / DELETE / TRUNCATE refuzate)

Excepție: ștergerea prin retenție a intrărilor mai vechi de un an (audit-retention).

Revision ID: 012
Revises: 011
Create Date: 2026-10-15
"""
from typing import Sequence, Union
from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
CREATE OR REPLACE FUNCTION audit_logs_protect() RETURNS trigger AS $$
BEGIN
    -- Singura excepție: ștergerea automată la expirarea retenției (minimum un an)
    IF TG_OP = 'DELETE' AND OLD.timestamp < NOW() - INTERVAL '365 days' THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'Jurnalul de audit nu poate fi modificat (%).', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;
    """)
    op.execute("DROP TRIGGER IF EXISTS audit_logs_protect_rows ON audit_logs")
    op.execute("DROP TRIGGER IF EXISTS audit_logs_protect_truncate ON audit_logs")
    op.execute("""
        CREATE TRIGGER audit_logs_protect_rows BEFORE UPDATE OR DELETE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION audit_logs_protect()
    """)
    op.execute("""
        CREATE TRIGGER audit_logs_protect_truncate BEFORE TRUNCATE ON audit_logs
            FOR EACH STATEMENT EXECUTE FUNCTION audit_logs_protect()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_logs_protect_rows ON audit_logs")
    op.execute("DROP TRIGGER IF EXISTS audit_logs_protect_truncate ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS audit_logs_protect()")
