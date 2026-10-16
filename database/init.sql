-- ============================================================
-- init.sql — Schema completă și actualizată a bazei de date
-- ============================================================
-- Rulează O SINGURĂ DATĂ când PostgreSQL pornește cu volum gol.
-- Conține schema la zi — nu mai e nevoie de fișiere de migrare
-- separate montate în docker-entrypoint-initdb.d.
--
-- Upgrade-uri pe deployment-uri existente → Alembic (services/api/alembic/)
-- ============================================================

-- Activăm extensia pentru UUID (vine cu PostgreSQL, trebuie doar activată)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Activăm extensia pentru full-text search în română și engleză
CREATE EXTENSION IF NOT EXISTS "unaccent";  -- elimină diacritice la search (ș=s, ț=t)

-- Activăm pgvector pentru căutare semantică (embeddings)
-- Necesită imaginea pgvector/pgvector:pg15 în docker-compose
CREATE EXTENSION IF NOT EXISTS vector;

-- Full-text search în română, insensibil la diacritice: „sedinta” găsește „ședința”
-- (și invers — Whisper omite uneori diacriticele). unaccent înaintea stemmer-ului.
CREATE TEXT SEARCH CONFIGURATION romanian_unaccent (COPY = romanian);
ALTER TEXT SEARCH CONFIGURATION romanian_unaccent
    ALTER MAPPING FOR word, hword, hword_part, asciiword, asciihword, hword_asciipart
    WITH unaccent, romanian_stem;

-- ============================================================
-- TIPURI CUSTOM (ENUM) — Valori predefinite
-- ============================================================

-- Statusurile unei înregistrări audio
CREATE TYPE recording_status AS ENUM (
    'session_registered', -- sesiune pre-înregistrată de client, niciun fișier audio încă
    'uploaded',           -- fișierul a ajuns în sistem
    'validating',         -- se verifică integritatea
    'queued',             -- în așteptare pentru transcriere
    'transcribing',       -- transcriere în curs
    'completed',          -- transcriere finalizată
    'failed',             -- eroare la procesare
    'archived',           -- arhivat (nu mai e activ)
    'cancelled'           -- transcriere anulată din interfață (poate fi repornită)
);

-- Statusurile unui job de transcriere
CREATE TYPE transcription_status AS ENUM (
    'pending',
    'processing',
    'completed',
    'failed',
    'cancelled'
);

-- Formatele audio suportate
CREATE TYPE audio_format AS ENUM (
    'wav',     -- cel mai bun pentru STT (fără compresie)
    'mp3',     -- comprimat, mai mic
    'm4a',     -- format Apple
    'ogg',     -- open source
    'flac',    -- compresie fără pierderi
    'webm',    -- format web
    'unknown'  -- placeholder până la upload fișier
);

-- Tipuri de acțiuni pentru audit
CREATE TYPE audit_action AS ENUM (
    'CREATE',           -- utilizator creat
    'UPDATE',           -- utilizator / resursă actualizată
    'UPLOAD',           -- fișier nou încărcat
    'VIEW',             -- transcript vizualizat
    'SEARCH',           -- căutare efectuată
    'EXPORT',           -- transcript exportat
    'DELETE',           -- înregistrare ștearsă
    'TRANSCRIBE',       -- transcriere pornită
    'LOGIN',            -- autentificare user
    'RETENTION_DELETE', -- șters automat de politica de retenție
    'SEMANTIC_SEARCH'   -- căutare semantică (embeddings)
);

-- ============================================================
-- TABELUL PRINCIPAL: recordings
-- ============================================================
CREATE TABLE recordings (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Informații despre ședință
    title           VARCHAR(500) NOT NULL,
    description     TEXT,
    meeting_date    DATE NOT NULL,
    location        VARCHAR(255),
    participants    TEXT[],
    -- Asocierea vorbitorilor din diarizare cu persoane: {"SPEAKER_00": "Ion Popescu", ...}
    speaker_mapping JSONB DEFAULT '{}',

    -- Informații tehnice despre fișierul audio
    original_filename   VARCHAR(500) NOT NULL,
    file_path           VARCHAR(1000) NOT NULL,
    file_size_bytes     BIGINT NOT NULL,
    file_hash_sha256    CHAR(64) NOT NULL UNIQUE,
    audio_format        audio_format NOT NULL,
    duration_seconds    INTEGER,
    sample_rate_hz      INTEGER,
    channels            SMALLINT DEFAULT 1,

    -- Status și procesare
    status          recording_status NOT NULL DEFAULT 'uploaded',
    error_message   TEXT,

    -- Timestamps
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    retain_until    DATE,

    -- Metadate extra (flexibil, pentru viitor)
    metadata        JSONB DEFAULT '{}'::jsonb,

    -- Suport sesiuni multi-segment: toate segmentele aceleiași ședințe
    -- au același session_id. NULL = înregistrare fără sesiune explicită.
    session_id          UUID,

    -- Timestamp-ul ultimului segment primit pentru această sesiune.
    -- Session Watcher verifică dacă NOW() - last_segment_at > SESSION_TIMEOUT
    -- pentru a decide când să lanseze transcrierea pe audio-ul concatenat.
    -- NULL = înregistrare simplă (fără sesiune) sau sesiune deja dispatchată.
    last_segment_at     TIMESTAMPTZ
);

CREATE INDEX idx_recordings_status ON recordings(status);
CREATE INDEX idx_recordings_meeting_date ON recordings(meeting_date DESC);
CREATE INDEX idx_recordings_created_at ON recordings(created_at DESC);
CREATE INDEX idx_recordings_file_hash ON recordings(file_hash_sha256);

-- Un session_id → o singură înregistrare principală
CREATE UNIQUE INDEX idx_recordings_session_id
    ON recordings(session_id)
    WHERE session_id IS NOT NULL;

-- Index pentru Session Watcher: caută sesiuni cu status='queued' neexpirate
CREATE INDEX idx_recordings_session_watcher
    ON recordings (last_segment_at)
    WHERE session_id IS NOT NULL AND status = 'queued';

-- ============================================================
-- TABELUL: recording_audio_segments
-- ============================================================
-- Segmentele audio suplimentare ale unei sesiuni multi-part.
-- Segmentul 0 este fișierul principal (recordings.file_path).
-- Segmentele 1, 2, ... sunt stocate aici.
CREATE TABLE recording_audio_segments (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    recording_id     UUID NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    segment_index    INTEGER NOT NULL,
    file_path        VARCHAR(1000) NOT NULL,
    file_hash_sha256 CHAR(64),
    file_size_bytes  BIGINT,
    duration_seconds INTEGER,
    status           VARCHAR(20) NOT NULL DEFAULT 'queued',
    error_message    TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT unique_audio_segment UNIQUE (recording_id, segment_index)
);

CREATE INDEX idx_audio_segments_recording_id ON recording_audio_segments(recording_id);

-- ============================================================
-- TABELUL: transcripts
-- ============================================================
CREATE TABLE transcripts (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    recording_id    UUID NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,

    status          transcription_status NOT NULL DEFAULT 'pending',
    language        VARCHAR(10) DEFAULT 'ro',
    model_used      VARCHAR(100),
    model_version   VARCHAR(50),

    word_count          INTEGER DEFAULT 0,
    confidence_avg      DECIMAL(4,3),
    processing_time_sec INTEGER,
    -- Durata etapelor (secunde); diarizarea în paralel se suprapune cu transcrierea
    transcription_sec    NUMERIC(8,1),
    alignment_sec        NUMERIC(8,1),
    diarization_sec      NUMERIC(8,1),
    diarization_parallel BOOLEAN NOT NULL DEFAULT FALSE,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,

    error_message   TEXT,

    CONSTRAINT unique_active_transcript UNIQUE (recording_id)
);

CREATE INDEX idx_transcripts_recording_id ON transcripts(recording_id);
CREATE INDEX idx_transcripts_status ON transcripts(status);

-- ============================================================
-- TABELUL: transcript_segments
-- ============================================================
CREATE TABLE transcript_segments (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    transcript_id   UUID NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,

    segment_index   INTEGER NOT NULL,
    start_time      DECIMAL(10,3) NOT NULL,
    end_time        DECIMAL(10,3) NOT NULL,

    text            TEXT NOT NULL,
    confidence      DECIMAL(4,3),
    language        VARCHAR(10),
    speaker_id      VARCHAR(50),

    -- Coloană generată automat pentru full-text search pe segment
    search_vector   TSVECTOR GENERATED ALWAYS AS (
                        to_tsvector('romanian_unaccent', coalesce(text, ''))
                    ) STORED,

    -- Embedding semantic (generat de search-indexer) și modelul care l-a produs:
    -- vectorii de la modele / setări diferite nu sunt comparabili
    embedding       vector(384),
    embedding_model VARCHAR(150),

    CONSTRAINT unique_segment_index UNIQUE (transcript_id, segment_index)
);

CREATE INDEX idx_segments_transcript_id ON transcript_segments(transcript_id);
CREATE INDEX idx_segments_start_time ON transcript_segments(transcript_id, start_time);

-- GIN index pentru full-text search pe segmente individuale
CREATE INDEX idx_transcript_segments_search_vector
    ON transcript_segments USING GIN (search_vector);

-- HNSW index pentru căutare semantică (cosine distance)
CREATE INDEX idx_segments_embedding ON transcript_segments
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- ============================================================
-- TABELUL: audit_logs
-- ============================================================
CREATE TABLE audit_logs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    user_id         UUID,
    user_ip         INET NOT NULL,
    user_agent      VARCHAR(500),

    action          audit_action NOT NULL,
    resource_type   VARCHAR(100),
    resource_id     UUID,

    details         JSONB DEFAULT '{}'::jsonb,
    success         BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX idx_audit_timestamp ON audit_logs(timestamp DESC);
CREATE INDEX idx_audit_resource ON audit_logs(resource_type, resource_id);
CREATE INDEX idx_audit_action ON audit_logs(action);

-- Jurnalul se poate doar completa: UPDATE / DELETE / TRUNCATE sunt refuzate,
-- cu excepția ștergerii prin retenție a intrărilor mai vechi de un an.
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

CREATE TRIGGER audit_logs_protect_rows BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION audit_logs_protect();
CREATE TRIGGER audit_logs_protect_truncate BEFORE TRUNCATE ON audit_logs
    FOR EACH STATEMENT EXECUTE FUNCTION audit_logs_protect();

-- ============================================================
-- TABELUL: users
-- ============================================================
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username        VARCHAR(100) UNIQUE NOT NULL,
    email           VARCHAR(255) UNIQUE NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    full_name       VARCHAR(255),
    is_active       BOOLEAN DEFAULT TRUE,
    role            VARCHAR(20) NOT NULL DEFAULT 'operator',
    must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    last_login      TIMESTAMPTZ,
    CONSTRAINT chk_users_role CHECK (role IN ('admin', 'operator', 'participant'))
);

-- ============================================================
-- TABELUL: app_settings
-- ============================================================
-- Setări de funcționare schimbate din interfața de administrare.
-- O cheie lipsă = se folosește valoarea din .env (variabila de mediu).
-- Serviciile citesc tabelul la fiecare job / verificare.
CREATE TABLE app_settings (
    key         VARCHAR(100) PRIMARY KEY,
    value       JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by  UUID REFERENCES users(id) ON DELETE SET NULL
);

-- ============================================================
-- TABELUL: recording_participants
-- ============================================================
CREATE TABLE recording_participants (
    recording_id  UUID NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    linked_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    linked_by     UUID REFERENCES users(id),
    PRIMARY KEY (recording_id, user_id)
);

CREATE INDEX idx_recording_participants_user_id ON recording_participants(user_id);

-- ============================================================
-- TRIGGER: actualizează updated_at automat pe recordings
-- ============================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_recordings_updated_at
    BEFORE UPDATE ON recordings
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- TRIGGER: NOTIFY când transcrierea e completă
-- ============================================================
-- Search Indexer ascultă canalul 'transcript_ready' și generează
-- embeddings imediat ce STT Worker finalizează transcrierea.
CREATE OR REPLACE FUNCTION notify_transcript_ready()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'completed'
       AND (OLD.status IS DISTINCT FROM 'completed') THEN
        PERFORM pg_notify('transcript_ready', NEW.id::text);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER transcript_completed_notify
    AFTER UPDATE ON transcripts
    FOR EACH ROW
    EXECUTE FUNCTION notify_transcript_ready();

-- ============================================================
-- DATE INIȚIALE (Seed Data)
-- ============================================================
-- Conturi implicite: admin/admin123 și operator/operator123.
-- must_change_password = TRUE → parola trebuie schimbată la primul login.
-- Installerul (install-offline.sh / install.sh) setează parola adminului și
-- dezactivează 'operator' dacă are încă parola implicită (src/cli/create_admin.py).
INSERT INTO users (username, email, full_name, password_hash, is_active, role, must_change_password) VALUES
(
    'admin',
    'admin@meetrec.local',
    'Administrator',
    '$2b$12$gx/JCPvsqzV45DZK4/0YOeJLI0AlTHlHpyt2kLsGMgA3.dLoOMe5.',
    TRUE,
    'admin',
    TRUE
),
(
    'operator',
    'operator@meetrec.local',
    'Operator Ședințe',
    '$2b$12$bLhDb8uFQTKUqrCj6KP0LOplCIEvt6hTe9ChX7asGbVZbhl6L1kZe',
    TRUE,
    'operator',
    TRUE
);

-- ============================================================
-- COMENTARII DOCUMENTARE
-- ============================================================
COMMENT ON TABLE recordings IS 'Înregistrări audio ale ședințelor';
COMMENT ON TABLE recording_audio_segments IS 'Segmente audio suplimentare pentru sesiuni multi-part';
COMMENT ON TABLE transcripts IS 'Transcripturi generate din înregistrări audio';
COMMENT ON TABLE transcript_segments IS 'Segmente individuale (fraze) cu timestamps';
COMMENT ON TABLE audit_logs IS 'Log de audit - toate acțiunile utilizatorilor';
COMMENT ON COLUMN transcript_segments.confidence IS 'Scorul de încredere Whisper: 0.0 = nesigur, 1.0 = sigur';
COMMENT ON COLUMN recordings.file_hash_sha256 IS 'Hash SHA256 pentru verificarea integrității și deduplicare';
COMMENT ON COLUMN recordings.session_id IS 'UUID sesiune multi-segment; toate segmentele aceleiași ședințe au același session_id';
