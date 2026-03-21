-- ============================================================
-- Migration 003: User management support (must_change_password + audit actions)
-- ============================================================
-- Motiv:
-- 1) utilizatorii creați de admin primesc parolă temporară și trebuie
--    să o schimbe la primul login.
-- 2) audit log trebuie să poată salva explicit CREATE / UPDATE.
--
-- Rulează:
--   psql -U mt_user -d meeting_transcriber -f 003_add_user_mgmt_fields_and_audit_actions.sql
-- ============================================================

ALTER TABLE users
ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'CREATE';
ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'UPDATE';
