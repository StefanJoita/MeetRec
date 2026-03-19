-- ============================================================
-- Migration 002: Trigger pentru actualizarea search_vector
-- ============================================================
-- Motiv: trigger-ul din init.sql nu a fost creat pe DB-ul existent
-- (init.sql rulează doar la prima creare a bazei de date).
-- Fără acest trigger, căutarea full-text nu funcționează pentru
-- înregistrările noi.
--
-- Aplicat manual pe DB-ul curent la: 2026-03-19
-- Rulează: psql -U mt_user -d meeting_transcriber -f 002_add_search_vector_trigger.sql
-- ============================================================

-- Funcția care agregă textul segmentelor și actualizează search_vector
CREATE OR REPLACE FUNCTION fn_update_search_vector()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE transcripts
    SET search_vector = (
        SELECT to_tsvector('romanian', string_agg(text, ' '))
        FROM transcript_segments
        WHERE transcript_id = NEW.transcript_id
    )
    WHERE id = NEW.transcript_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger-ul care apelează funcția după fiecare INSERT în transcript_segments
DROP TRIGGER IF EXISTS update_search_vector_on_segment ON transcript_segments;
CREATE TRIGGER update_search_vector_on_segment
    AFTER INSERT ON transcript_segments
    FOR EACH ROW EXECUTE FUNCTION fn_update_search_vector();

-- Backfill: populează search_vector pentru transcriptele completate existente
UPDATE transcripts t
SET search_vector = (
    SELECT to_tsvector('romanian', string_agg(seg.text, ' '))
    FROM transcript_segments seg
    WHERE seg.transcript_id = t.id
)
WHERE t.status = 'completed'
  AND t.search_vector IS NULL;
