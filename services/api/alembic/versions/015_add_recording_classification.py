"""Nivelul de clasificare al fiecărei înregistrări

N (neclasificat), SSv (secret de serviciu), S (secret), SS (strict secret).
Se alege la încărcare / la pornirea înregistrării din browser; apare în listă,
în detalii, în antetul exporturilor și în numele fișierelor exportate.
Înregistrările existente devin N.

Revision ID: 015
Revises: 014
Create Date: 2026-10-28
"""
from typing import Sequence, Union
from alembic import op

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE recordings ADD COLUMN IF NOT EXISTS classification VARCHAR(3) NOT NULL DEFAULT 'N'")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'recordings_classification_check') THEN
                ALTER TABLE recordings ADD CONSTRAINT recordings_classification_check
                    CHECK (classification IN ('N', 'SSv', 'S', 'SS'));
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE recordings DROP CONSTRAINT IF EXISTS recordings_classification_check")
    op.execute("ALTER TABLE recordings DROP COLUMN IF EXISTS classification")
