-- ============================================================
-- init.sql — Schema inițială a bazei de date
-- ============================================================
-- Rulează O SINGURĂ DATĂ când PostgreSQL pornește prima oară.
-- Modificările ulterioare merg în database/migrations/
--
-- SQL 101:
--   UUID = identificator unic universal (mai sigur decât 1,2,3...)
--          De ce UUID și nu INTEGER AUTO INCREMENT?
--          → Nu expune "câte înregistrări avem" (securitate)
--          → Poți genera ID-ul înainte de inserare în DB
--          → Funcționează cu sisteme distribuite
-- ============================================================

-- Activăm extensia pentru UUID (vine cu PostgreSQL, trebuie doar activată)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Activăm extensia pentru full-text search în română și engleză
CREATE EXTENSION IF NOT EXISTS "unaccent";  -- elimină diacritice la search (ș=s, ț=t)

-- Activăm pgvector pentru căutare semantică (embeddings)
-- Necesită imaginea pgvector/pgvector:pg15 în docker-compose
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================
-- TIPURI CUSTOM (ENUM) — Valori predefinite
-- ============================================================
-- În loc de "status VARCHAR" unde cineva poate pune orice,
-- definim exact ce valori sunt permise.
-- Ca un dropdown vs un câmp liber de text.

-- Statusurile unei înregistrări audio
CREATE TYPE recording_status AS ENUM (
    'uploaded',       -- fișierul a ajuns în sistem
    'validating',     -- se verifică integritatea
    'queued',         -- în așteptare pentru transcriere
    'transcribing',   -- transcriere în curs
    'completed',      -- transcriere finalizată
    'failed',         -- eroare la procesare
    'archived'        -- arhivat (nu mai e activ)
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
    'CREATE',         -- utilizator creat
    'UPDATE',         -- utilizator / resursă actualizată
    'UPLOAD',         -- fișier nou încărcat
    'VIEW',           -- transcript vizualizat
    'SEARCH',         -- căutare efectuată
    'EXPORT',         -- transcript exportat
    'DELETE',         -- înregistrare ștearsă
    'TRANSCRIBE',     -- transcriere pornită
    'LOGIN',          -- autentificare user
    'RETENTION_DELETE', -- șters automat de politica de retenție
    'SEMANTIC_SEARCH'   -- căutare semantică (embeddings)
);

-- ============================================================
-- TABELUL PRINCIPAL: recordings
-- ============================================================
-- Stochează metadata despre fiecare înregistrare audio.
-- Fișierul audio fizic e pe NFS, nu în baza de date!
-- (Regula: DB = metadata, NFS = fișiere binare mari)

CREATE TABLE recordings (
    -- Identificator unic generat automat
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Informații despre ședință
    title           VARCHAR(500) NOT NULL,  -- "Ședința Consiliului Local - 15 Ian 2024"
    description     TEXT,                   -- detalii opționale
    meeting_date    DATE NOT NULL,          -- data ședinței (nu când s-a uploadat!)
    location        VARCHAR(255),           -- "Sala Mare, Etaj 2"
    participants    TEXT[],                 -- array de nume: {'Ion Ionescu', 'Maria Pop'}

    -- Informații tehnice despre fișierul audio
    original_filename   VARCHAR(500) NOT NULL,  -- "sedinta_15ian.mp3"
    file_path           VARCHAR(1000) NOT NULL, -- "/data/processed/2024/01/uuid.mp3"
    file_size_bytes     BIGINT NOT NULL,
    file_hash_sha256    CHAR(64) NOT NULL UNIQUE, -- SHA256 = 64 caractere hex
    -- UNIQUE pe hash = nu poți uploada același fișier de două ori
    audio_format        audio_format NOT NULL,
    duration_seconds    INTEGER,               -- durată în secunde (calculată la ingest)
    sample_rate_hz      INTEGER,               -- 44100, 48000, etc.
    channels            SMALLINT DEFAULT 1,    -- 1=mono, 2=stereo

    -- Status și procesare
    status          recording_status NOT NULL DEFAULT 'uploaded',
    error_message   TEXT,                  -- dacă status='failed', de ce?

    -- Timestamps (toate în UTC, afișate în Europe/Bucharest)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),  -- când a ajuns în sistem
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),  -- ultima modificare
    -- Retenție: când trebuie ștearsă înregistrarea
    retain_until    DATE,                  -- NULL = nu se șterge automat

    -- Metadate extra (flexibil, pentru viitor)
    metadata        JSONB DEFAULT '{}'::jsonb
    -- Exemplu: {"camera": "GoPro", "room_number": "101"}
);

-- Indexuri pentru recordings (accelerează query-urile frecvente)
-- Fără index: PostgreSQL scanează TOATĂ tabela (lent!)
-- Cu index: PostgreSQL sare direct la rândul corect (rapid!)
CREATE INDEX idx_recordings_status ON recordings(status);
CREATE INDEX idx_recordings_meeting_date ON recordings(meeting_date DESC);
CREATE INDEX idx_recordings_created_at ON recordings(created_at DESC);
CREATE INDEX idx_recordings_file_hash ON recordings(file_hash_sha256);

-- ============================================================
-- TABELUL: transcripts
-- ============================================================
-- O înregistrare poate avea MAXIM UN transcript activ
-- (relație 1:1, dar separăm pentru claritate)

CREATE TABLE transcripts (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    recording_id    UUID NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    -- ON DELETE CASCADE: dacă ștergem înregistrarea, transcriptul se șterge automat

    -- Informații despre transcriere
    status          transcription_status NOT NULL DEFAULT 'pending',
    language        VARCHAR(10) DEFAULT 'ro',   -- 'ro', 'en', 'ro-en' (bilingv)
    model_used      VARCHAR(100),               -- 'whisper-medium', 'whisper-large-v3'
    model_version   VARCHAR(50),

    -- Statistici
    word_count          INTEGER DEFAULT 0,
    confidence_avg      DECIMAL(4,3),           -- 0.000 - 1.000
    processing_time_sec INTEGER,                -- cât a durat transcriere (secunde)

    -- Full-text search vector (generat automat din segmente)
    -- Aceasta e "magia" PostgreSQL pentru căutare rapidă în text
    search_vector   TSVECTOR,

    -- Timestamps
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMPTZ,       -- când a început procesarea
    completed_at    TIMESTAMPTZ,       -- când s-a terminat

    error_message   TEXT,

    -- Constrângere: o înregistrare are maxim un transcript activ
    CONSTRAINT unique_active_transcript UNIQUE (recording_id)
);

CREATE INDEX idx_transcripts_recording_id ON transcripts(recording_id);
CREATE INDEX idx_transcripts_status ON transcripts(status);
-- Index special pentru full-text search (GIN = cel mai bun pentru TSVECTOR)
CREATE INDEX idx_transcripts_search ON transcripts USING GIN(search_vector);

-- ============================================================
-- TABELUL: transcript_segments
-- ============================================================
-- Fiecare rând = o propoziție/frază cu timestamp-urile ei
-- Acestea permit sincronizarea audio ↔ text în UI
-- (click pe o frază → audio sare la acel moment)

CREATE TABLE transcript_segments (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    transcript_id   UUID NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,

    -- Poziția în transcript
    segment_index   INTEGER NOT NULL,   -- 0, 1, 2, ... (ordinea frazelor)
    start_time      DECIMAL(10,3) NOT NULL,  -- 12.500 = 12 secunde și 500ms
    end_time        DECIMAL(10,3) NOT NULL,

    -- Conținutul
    text            TEXT NOT NULL,
    confidence      DECIMAL(4,3),       -- 0.850 = 85% încredere Whisper
    language        VARCHAR(10),        -- 'ro' sau 'en' (pentru segmente bilingve)

    -- Speaker diarization (opțional, pentru viitor)
    -- Identifică cine vorbește în fiecare segment
    speaker_id      VARCHAR(50),        -- 'SPEAKER_00', 'SPEAKER_01', etc.

    -- Embedding semantic (generat de search-indexer cu sentence-transformers)
    -- vector(384) = paraphrase-multilingual-MiniLM-L12-v2
    -- NULL = segmentul nu a fost încă indexat semantic
    embedding       vector(384),

    -- Constrângere: în același transcript, index-ul e unic
    CONSTRAINT unique_segment_index UNIQUE (transcript_id, segment_index)
);

CREATE INDEX idx_segments_transcript_id ON transcript_segments(transcript_id);
CREATE INDEX idx_segments_start_time ON transcript_segments(transcript_id, start_time);

-- Index HNSW pentru căutare semantică (cosine distance)
-- HNSW = Hierarchical Navigable Small World — cel mai rapid pentru ANN search
-- vector_cosine_ops = optimizat pentru vectori normalizați (cum generăm noi)
CREATE INDEX idx_segments_embedding ON transcript_segments
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
-- m=16, ef_construction=64 = echilibru bun între calitate și viteză de build

-- ============================================================
-- TABELUL: audit_logs
-- ============================================================
-- Înregistrează ORICE acțiune importantă în sistem.
-- Cerință legală: cine a văzut/exportat ce, și când.
-- IMPORTANT: Audit logs NU se șterg (sau se șterg după mulți ani)

CREATE TABLE audit_logs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Cine a efectuat acțiunea
    user_id         UUID,               -- NULL dacă nu e autentificat
    user_ip         INET NOT NULL,      -- tipul INET = validează automat IP-uri
    user_agent      VARCHAR(500),       -- browserul utilizatorului

    -- Ce acțiune
    action          audit_action NOT NULL,
    resource_type   VARCHAR(100),       -- 'recording', 'transcript', 'export'
    resource_id     UUID,               -- ID-ul resursei afectate

    -- Detalii extra în format JSON (flexibil)
    details         JSONB DEFAULT '{}'::jsonb,
    -- Exemple:
    -- {"format": "pdf", "filename": "export_sedinta.pdf"}
    -- {"search_query": "buget 2024", "results_count": 5}
    -- {"error": "fișier corupt", "file": "sedinta.mp3"}

    -- Rezultatul acțiunii
    success         BOOLEAN NOT NULL DEFAULT TRUE
);

-- Audit logs: indexăm pe timestamp (cele mai comune query-uri sunt "ultimele N")
CREATE INDEX idx_audit_timestamp ON audit_logs(timestamp DESC);
CREATE INDEX idx_audit_resource ON audit_logs(resource_type, resource_id);
CREATE INDEX idx_audit_action ON audit_logs(action);

-- ============================================================
-- TRIGGER: actualizează updated_at automat
-- ============================================================
-- Un trigger = cod care rulează automat când se întâmplă ceva în DB
-- Fără trigger: ar trebui să trimitem updated_at de fiecare dată din cod

-- $$ = delimiter pentru corpul funcției; language plpgsql = limbajul procedural PostgreSQL
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    -- NEW = rândul nou (după UPDATE)
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Aplicăm trigger-ul pe tabela recordings
CREATE TRIGGER update_recordings_updated_at
    BEFORE UPDATE ON recordings           -- rulează ÎNAINTE de UPDATE
    FOR EACH ROW                          -- pentru fiecare rând modificat
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- TRIGGER: actualizează search_vector automat
-- ============================================================
-- Când se inserează/modifică segmente, actualizează indexul de căutare
-- Fără asta, ar trebui să reindexăm manual după fiecare transcriere

CREATE OR REPLACE FUNCTION update_transcript_search_vector()
RETURNS TRIGGER AS $$
BEGIN
    -- Actualizăm search_vector în transcripts din segmentele asociate
    UPDATE transcripts
    SET search_vector = (
        SELECT
            -- to_tsvector = transformă text în format indexabil
            -- 'romanian' = tokenizare în limba română
            -- || = concatenare de tsvectors
            setweight(to_tsvector('romanian', COALESCE(string_agg(
                ts.text, ' '
            ), '')), 'A')  -- 'A' = prioritate maximă în search ranking
        FROM transcript_segments ts
        WHERE ts.transcript_id = NEW.transcript_id
    )
    WHERE id = NEW.transcript_id;

    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_search_vector_on_segment
    AFTER INSERT OR UPDATE ON transcript_segments
    FOR EACH ROW
    EXECUTE FUNCTION update_transcript_search_vector();

-- ============================================================
-- TRIGGER: NOTIFY când transcrierea e completă
-- ============================================================
-- Când STT Worker setează status='completed' pe un transcript,
-- triggerul apelează pg_notify('transcript_ready', transcript_id).
-- Search Indexer ascultă acest canal și generează embeddings imediat.
--
-- De ce trigger în DB și nu în codul Python?
--   - Garantat: chiar dacă STT Worker crape după UPDATE, notificarea
--     a fost deja trimisă (în aceeași tranzacție → atomicitate)
--   - Simplu: o linie de SQL vs. cod Python suplimentar în worker

CREATE OR REPLACE FUNCTION notify_transcript_ready()
RETURNS TRIGGER AS $$
BEGIN
    -- Notificăm DOAR când trecem în 'completed' (nu la alte status updates)
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
-- Câțiva utilizatori de test (în producție, se creează prin UI)
-- Parola hash: bcrypt('admin123') — SCHIMBĂ în producție!

CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username        VARCHAR(100) UNIQUE NOT NULL,
    email           VARCHAR(255) UNIQUE NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,  -- NICIODATĂ parola în clar!
    full_name       VARCHAR(255),
    is_active       BOOLEAN DEFAULT TRUE,
    role            VARCHAR(20) NOT NULL DEFAULT 'operator',
    must_change_password BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    last_login      TIMESTAMPTZ,
    CONSTRAINT chk_users_role CHECK (role IN ('admin', 'operator', 'participant'))
);

CREATE TABLE recording_participants (
    recording_id  UUID NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    linked_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    linked_by     UUID REFERENCES users(id),
    PRIMARY KEY (recording_id, user_id)
);

CREATE INDEX idx_recording_participants_user_id ON recording_participants(user_id);

-- Utilizatori de test (SCHIMBĂ parolele în producție!)
-- admin123  → hash bcrypt mai jos
-- operator123 → hash bcrypt mai jos
INSERT INTO users (username, email, full_name, password_hash, is_active, role, must_change_password) VALUES
(
    'admin',
    'admin@meetrec.local',
    'Administrator',
    '$2b$12$gx/JCPvsqzV45DZK4/0YOeJLI0AlTHlHpyt2kLsGMgA3.dLoOMe5.',
    TRUE,
    'admin',
    FALSE
),
(
    'operator',
    'operator@meetrec.local',
    'Operator Ședințe',
    '$2b$12$bLhDb8uFQTKUqrCj6KP0LOplCIEvt6hTe9ChX7asGbVZbhl6L1kZe',
    TRUE,
    'operator',
    FALSE
);

-- Comentariu vizibil în DB pentru documentare
COMMENT ON TABLE recordings IS 'Înregistrări audio ale ședințelor';
COMMENT ON TABLE transcripts IS 'Transcripturi generate din înregistrări audio';
COMMENT ON TABLE transcript_segments IS 'Segmente individuale (fraze) cu timestamps';
COMMENT ON TABLE audit_logs IS 'Log de audit - toate acțiunile utilizatorilor';
COMMENT ON COLUMN transcript_segments.confidence IS 'Scorul de încredere Whisper: 0.0 = nesigur, 1.0 = sigur';
COMMENT ON COLUMN recordings.file_hash_sha256 IS 'Hash SHA256 pentru verificarea integrității și deduplicare';