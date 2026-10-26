import client from './client'
import type { TokenResponse } from './types'

// Înregistrarea din browser folosește API-ul de sesiune multi-segment:
// /session/create → /upload (câte un segment) → /session/{id}/complete.

export interface SessionMetadata {
  title: string
  meeting_date: string
  description?: string
  participants?: string
  location?: string
}

export async function createRecordingSession(meta: SessionMetadata): Promise<string> {
  const { data } = await client.post<{ session_id: string; recording_id: string }>('/inbox/session/create', meta)
  return data.session_id
}

export async function uploadSessionSegment(sessionId: string, index: number, blob: Blob): Promise<void> {
  const form = new FormData()
  form.append('file', blob, `inregistrare_${sessionId.slice(0, 8)}_${String(index).padStart(3, '0')}.wav`)
  form.append('session_id', sessionId)
  form.append('segment_index', String(index))
  await client.post('/inbox/upload', form, { headers: { 'Content-Type': 'multipart/form-data' } })
}

export async function completeRecordingSession(sessionId: string, totalSegments: number): Promise<string> {
  const { data } = await client.post<{ status: string; recording_id: string }>(
    `/inbox/session/${sessionId}/complete`,
    { total_segments: totalSegments },
  )
  return data.recording_id
}

/** Token nou, valabil încă o perioadă completă; salvat unde îl citește clientul axios. */
export async function refreshAccessToken(): Promise<void> {
  const { data } = await client.post<TokenResponse>('/auth/refresh')
  localStorage.setItem('access_token', data.access_token)
}
