-- ============================================================
-- Migration 001: Adaugă valoarea 'unknown' în enum audio_format
-- ============================================================
-- Motiv: înregistrările create prin API (fără fișier audio) au nevoie
-- de un format placeholder până când fișierul este uploadat.
--
-- Aplicat manual pe DB-ul curent la: 2026-03-19
-- Rulează: psql -U mt_user -d meeting_transcriber -f 001_add_unknown_audio_format.sql
-- ============================================================

ALTER TYPE audio_format ADD VALUE IF NOT EXISTS 'unknown';
