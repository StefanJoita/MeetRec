-- ============================================================
-- 005_add_participant_role_and_links.sql
-- ============================================================
-- Aliniază schema SQL "database/migrations" cu migrația Alembic 005:
--   - users.role (admin/operator/participant)
--   - remove users.is_admin
--   - create recording_participants

ALTER TABLE users
ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'operator';

UPDATE users
SET role = 'admin'
WHERE is_admin = TRUE;

ALTER TABLE users
DROP COLUMN IF EXISTS is_admin;

ALTER TABLE users
DROP CONSTRAINT IF EXISTS chk_users_role;

ALTER TABLE users
ADD CONSTRAINT chk_users_role CHECK (role IN ('admin', 'operator', 'participant'));

CREATE TABLE IF NOT EXISTS recording_participants (
    recording_id  UUID NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    linked_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    linked_by     UUID REFERENCES users(id),
    PRIMARY KEY (recording_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_recording_participants_user_id
ON recording_participants(user_id);
