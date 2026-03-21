-- ============================================================
-- Seed 001: Utilizatori inițiali
-- ============================================================
-- Parole: admin123 / operator123
-- IMPORTANT: Schimbă parolele înainte de deployment în producție!
--
-- Generare hash nou (Python):
--   from passlib.context import CryptContext
--   ctx = CryptContext(schemes=["bcrypt"])
--   print(ctx.hash("parola_noua"))
--
-- Rulează: psql -U mt_user -d meeting_transcriber -f 001_users.sql
-- ============================================================

INSERT INTO users (username, email, full_name, password_hash, is_active, is_admin, must_change_password)
VALUES
(
    'admin',
    'admin@meetrec.local',
    'Administrator',
    '$2b$12$gx/JCPvsqzV45DZK4/0YOeJLI0AlTHlHpyt2kLsGMgA3.dLoOMe5.',
    TRUE,
    TRUE,
    FALSE
),
(
    'operator',
    'operator@meetrec.local',
    'Operator Ședințe',
    '$2b$12$bLhDb8uFQTKUqrCj6KP0LOplCIEvt6hTe9ChX7asGbVZbhl6L1kZe',
    TRUE,
    FALSE,
    FALSE
)
ON CONFLICT (username) DO NOTHING;
