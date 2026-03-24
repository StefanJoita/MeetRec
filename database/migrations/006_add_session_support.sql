-- ============================================================
-- Migration 006: Suport sesiuni multi-segment
-- ============================================================
-- Motivație:
--   Un client de înregistrare poate trimite o ședință în mai multe
--   fișiere audio (segmente). Toate segmentele aceleiași ședințe au
--   același session_id și trebuie atașate la o singură înregistrare.
--
-- Modificări:
--   1. recordings.session_id  — identificatorul sesiunii (opțional)
--   2. recording_audio_segments — fișierele audio suplimentare
-- ============================================================

-- 1. Adaugă session_id pe recordings
ALTER TABLE recordings
    ADD COLUMN IF NOT EXISTS session_id UUID;

-- Index unic: un session_id → o singură înregistrare principală
CREATE UNIQUE INDEX IF NOT EXISTS idx_recordings_session_id
    ON recordings(session_id)
    WHERE session_id IS NOT NULL;

-- 2. Tabelă pentru segmentele audio suplimentare ale unei sesiuni
--    Segmentul 0 este fișierul principal (stocat în recordings.file_path).
--    Segmentele 1, 2, ... sunt stocate aici.
CREATE TABLE IF NOT EXISTS recording_audio_segments (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    recording_id     UUID NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    segment_index    INTEGER NOT NULL,         -- 0-based, ordinea în sesiune
    file_path        VARCHAR(1000) NOT NULL,
    file_hash_sha256 CHAR(64),
    file_size_bytes  BIGINT,
    duration_seconds INTEGER,
    status           VARCHAR(20) NOT NULL DEFAULT 'queued',
    error_message    TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT unique_audio_segment UNIQUE (recording_id, segment_index)
);

CREATE INDEX IF NOT EXISTS idx_audio_segments_recording_id
    ON recording_audio_segments(recording_id);
