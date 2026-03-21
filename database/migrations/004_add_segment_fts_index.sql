-- Migration 004: GIN Index for Full-Text Search on transcript_segments
-- ============================================================
-- Problema: to_tsvector('romanian', text) se calculează ON THE FLY
-- la fiecare căutare → full table scan pe transcript_segments.
--
-- Soluție: Adaugăm o coloană TSVECTOR generată automat + GIN index.
-- Aceasta elimină calculul la runtime și permite Index Scan în loc de Seq Scan.
--
-- CONCURRENTLY = crearea indexului nu blochează tabelul (sigur pe date existente)
-- ============================================================

-- Pas 1: Adaugă coloana search_vector (calculată automat de PostgreSQL)
ALTER TABLE transcript_segments
  ADD COLUMN IF NOT EXISTS search_vector TSVECTOR
    GENERATED ALWAYS AS (to_tsvector('romanian', coalesce(text, ''))) STORED;

-- Pas 2: Creează GIN index pe coloana nouă
-- CONCURRENTLY permite crearea fără lock pe tabel (pentru tabele mari cu date existente)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_transcript_segments_search_vector
  ON transcript_segments USING GIN (search_vector);

-- Pas 3: Comentariu pentru verificare (rulează după migrare)
-- EXPLAIN ANALYZE SELECT * FROM transcript_segments
--   WHERE search_vector @@ plainto_tsquery('romanian', 'test');
-- → Trebuie să apară: Bitmap Index Scan on idx_transcript_segments_search_vector
