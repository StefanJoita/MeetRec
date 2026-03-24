"""Add participant role and recording_participants table

Revision ID: 005
Revises: 004
Create Date: 2026-03-21

Motivație:
  - Adaugă rolul 'participant' pe lângă 'admin' și 'operator'
  - Înlocuiește coloana booleană is_admin cu un enum de roluri
  - Crează tabela de legătură recording_participants (recording ↔ user)
"""
from typing import Sequence, Union
from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Adaugă coloana role cu default 'operator'
    op.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'operator'
    """)

    # 2. Migrează datele existente: is_admin=TRUE → role='admin'
    # DO block condiționat: pe schema nouă (fără is_admin) instrucțiunea e sărită
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'users' AND column_name = 'is_admin'
            ) THEN
                UPDATE users SET role = 'admin' WHERE is_admin = TRUE;
            END IF;
        END; $$
    """)

    # 3. Elimină coloana is_admin (role este acum sursa de adevăr)
    op.execute("""
        ALTER TABLE users DROP COLUMN IF EXISTS is_admin
    """)

    # 4. Crează tabela de legătură recording ↔ participant_user
    op.execute("""
        CREATE TABLE IF NOT EXISTS recording_participants (
            recording_id  UUID NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
            user_id       UUID NOT NULL REFERENCES users(id)      ON DELETE CASCADE,
            linked_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            linked_by     UUID REFERENCES users(id),
            PRIMARY KEY (recording_id, user_id)
        )
    """)

    # 5. Index pentru query-ul "ce înregistrări am eu acces?" — O(log n) în loc de seq scan
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_recording_participants_user_id
        ON recording_participants(user_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_recording_participants_user_id")
    op.execute("DROP TABLE IF EXISTS recording_participants")

    # Restaurează is_admin din role
    op.execute("""
        ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE
    """)
    op.execute("""
        UPDATE users SET is_admin = TRUE WHERE role = 'admin'
    """)
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS role")
