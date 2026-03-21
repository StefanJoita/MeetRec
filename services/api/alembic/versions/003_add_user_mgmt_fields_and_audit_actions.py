"""User management: must_change_password + audit actions CREATE/UPDATE

Revision ID: 003
Revises: 002
Create Date: 2026-03-20

Motivație:
1) utilizatorii creați de admin primesc parolă temporară și trebuie
   să o schimbe la primul login.
2) audit log trebuie să poată salva explicit CREATE / UPDATE.
"""
from typing import Sequence, Union
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE
    """)

    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'CREATE'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'UPDATE'")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS must_change_password")
    # Nu putem șterge valorile din ENUM fără a recrea tipul
