// ============================================================
// TypeScript interfaces matching the Python Pydantic schemas.
// These are the single source of truth for API data shapes.
// ============================================================

export type RecordingStatus =
  | 'uploaded'
  | 'validating'
  | 'queued'
  | 'transcribing'
  | 'completed'
  | 'failed'
  | 'archived'

export type TranscriptStatus =
  | 'pending'
  | 'processing'
  | 'completed'
  | 'failed'
  | 'cancelled'

// ── List item (used in PaginatedRecordings) ─────────────────
export interface RecordingListItem {
  id: string
  title: string
  meeting_date: string           // "YYYY-MM-DD"
  audio_format: string           // "mp3", "wav", etc.
  duration_formatted: string     // "01:02:35"
  file_size_mb: number
  status: RecordingStatus
  created_at: string             // ISO 8601
  transcript_status: TranscriptStatus | null
}

// ── Full recording detail ────────────────────────────────────
export interface RecordingResponse {
  id: string
  title: string
  description: string | null
  meeting_date: string
  location: string | null
  participants: string[] | null
  original_filename: string
  file_size_bytes: number
  audio_format: string
  duration_seconds: number | null
  duration_formatted: string
  file_size_mb: number
  status: RecordingStatus
  error_message: string | null
  created_at: string
  updated_at: string
  retain_until: string | null
  transcript: TranscriptSummary | null
}

// ── Transcript summary (embedded in RecordingResponse) ───────
export interface TranscriptSummary {
  id: string
  status: TranscriptStatus
  word_count: number
  completed_at: string | null
}

// ── Paginated list response ──────────────────────────────────
export interface PaginatedRecordings {
  items: RecordingListItem[]
  total: number
  page: number
  page_size: number
  pages: number
}

// ── Transcript segment ───────────────────────────────────────
export interface TranscriptSegment {
  id: string
  segment_index: number
  start_time: number    // seconds, e.g. 12.500
  end_time: number
  text: string
  confidence: number | null
  speaker_id: string | null
  language: string | null
}

// ── Full transcript with segments ───────────────────────────
export interface TranscriptResponse {
  id: string
  recording_id: string
  status: TranscriptStatus
  language: string | null
  model_used: string | null
  word_count: number
  confidence_avg: number | null
  processing_time_sec: number | null
  created_at: string
  completed_at: string | null
  segments: TranscriptSegment[]
  full_text: string | null
}

// ── Search ───────────────────────────────────────────────────
export interface SearchResult {
  recording_id: string
  recording_title: string
  meeting_date: string
  segment_id: string
  start_time: number
  end_time: number
  text: string
  headline: string | null   // Contains <b>term</b> HTML from PostgreSQL ts_headline
  rank: number
}

export interface SearchResponse {
  query: string
  results: SearchResult[]
  total_results: number   // total înainte de LIMIT (pentru paginare)
  offset: number
  limit: number
  pages: number
  search_time_ms: number
}

// ── Input schemas ────────────────────────────────────────────
export interface RecordingUpdate {
  title?: string
  description?: string
  meeting_date?: string
  location?: string
  participants?: string[]
}

// ── Auth ─────────────────────────────────────────────────────
export interface User {
  id: string
  username: string
  email: string
  full_name: string
  is_admin: boolean
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
}

// ── Aliases (shorthand names used in components) ─────────────
export type Recording = RecordingResponse
export type Transcript = TranscriptResponse
export type Segment = TranscriptSegment

// ── Audit logs ───────────────────────────────────────────────
export interface AuditLog {
  id: string
  timestamp: string
  user_id?: string
  user_ip: string
  user_agent?: string
  action: string
  resource_type?: string
  resource_id?: string
  success: boolean
  details?: Record<string, unknown>
}

export interface PaginatedAuditLogs {
  items: AuditLog[]
  total: number
  page: number
  page_size: number
  pages: number
}

// ── API error shape ──────────────────────────────────────────
export interface ApiErrorBody {
  detail: string
}
