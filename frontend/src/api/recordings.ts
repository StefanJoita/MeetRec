import client from './client'
import type { PaginatedRecordings, RecordingResponse as Recording, ParticipantUserInfo } from './types'

export interface RecordingsParams {
  page?: number
  page_size?: number
  status?: string
  search?: string
  sort_by?: string
  sort_dir?: 'asc' | 'desc'
  sort_desc?: boolean
}

export interface InboxUploadResponse {
  message: string
  filename: string
}

export async function getRecordings(params: RecordingsParams = {}): Promise<PaginatedRecordings> {
  const { data } = await client.get<PaginatedRecordings>('/recordings', { params })
  return data
}

export async function getRecording(id: string): Promise<Recording> {
  const { data } = await client.get<Recording>(`/recordings/${id}`)
  return data
}

/**
 * Trimite fișierul audio în inbox-ul monitorizat de Ingest Service.
 * Ingest-ul preia automat, validează, creează înregistrarea și o pune în coadă.
 */
export async function dropFileToInbox(file: File): Promise<InboxUploadResponse> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await client.post<InboxUploadResponse>('/inbox/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function deleteRecording(id: string): Promise<void> {
  await client.delete(`/recordings/${id}`)
}

export async function retryTranscription(recordingId: string): Promise<void> {
  await client.post(`/transcripts/recording/${recordingId}/retry`)
}

export async function getAudioToken(recordingId: string): Promise<string> {
  const { data } = await client.get<{ token: string; expires_in: number }>(
    `/recordings/${recordingId}/audio-token`
  )
  return data.token
}

export function buildAudioUrl(recordingId: string, token: string): string {
  return `/api/v1/recordings/${recordingId}/audio?token=${encodeURIComponent(token)}`
}

// ── Participant management ────────────────────────────────────

export async function getRecordingParticipants(recordingId: string): Promise<ParticipantUserInfo[]> {
  const { data } = await client.get<ParticipantUserInfo[]>(`/recordings/${recordingId}/participants`)
  return data
}

export async function addRecordingParticipant(recordingId: string, userId: string): Promise<void> {
  await client.post(`/recordings/${recordingId}/participants`, { user_id: userId })
}

export async function removeRecordingParticipant(recordingId: string, userId: string): Promise<void> {
  await client.delete(`/recordings/${recordingId}/participants/${userId}`)
}
