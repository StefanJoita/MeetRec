import client from './client'
import type { PaginatedRecordings, RecordingResponse as Recording } from './types'

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

export function getAudioUrl(recordingId: string): string {
  // URL is returned without token; browser will send Bearer token via axios interceptor
  // If using native <audio>, fetch via Authorization header (see AudioPlayer.tsx)
  return `/api/v1/recordings/${recordingId}/audio`
}
