import client from './client'
import type { TranscriptResponse as Transcript } from './types'

export async function getTranscript(recordingId: string): Promise<Transcript> {
  const { data } = await client.get<Transcript>(`/transcripts/recording/${recordingId}`)
  return data
}
