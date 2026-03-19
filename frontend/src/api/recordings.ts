import client from './client'
import type { PaginatedRecordings, RecordingResponse as Recording } from './types'

export interface RecordingsParams {
  page?: number
  page_size?: number
  status?: string
  sort_by?: string
  sort_dir?: 'asc' | 'desc'
}

export async function getRecordings(params: RecordingsParams = {}): Promise<PaginatedRecordings> {
  const { data } = await client.get<PaginatedRecordings>('/recordings', { params })
  return data
}

export async function getRecording(id: string): Promise<Recording> {
  const { data } = await client.get<Recording>(`/recordings/${id}`)
  return data
}

export async function createRecording(body: {
  title: string
  meeting_date: string
  description?: string
  location?: string
  participants?: string[]
}): Promise<Recording> {
  const { data } = await client.post<Recording>('/recordings', body)
  return data
}

export async function uploadAudio(recordingId: string, file: File): Promise<void> {
  const form = new FormData()
  form.append('file', file)
  await client.post(`/recordings/${recordingId}/upload`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export async function deleteRecording(id: string): Promise<void> {
  await client.delete(`/recordings/${id}`)
}

export async function retryTranscription(recordingId: string): Promise<void> {
  await client.post(`/transcripts/recording/${recordingId}/retry`)
}

export function getAudioUrl(recordingId: string): string {
  const token = localStorage.getItem('access_token') ?? ''
  return `/api/v1/recordings/${recordingId}/audio?token=${token}`
}
