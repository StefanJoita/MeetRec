// frontend/src/hooks/useTranscript.ts
// Hook pentru transcriptul unei înregistrări.
// Se activează automat când înregistrarea ajunge la status 'completed'.

import { useQuery } from '@tanstack/react-query'
import { getTranscript } from '@/api/transcripts'
import type { TranscriptResponse, RecordingStatus } from '@/api/types'

export function useTranscript(
  recordingId: string | undefined,
  recordingStatus: RecordingStatus | undefined,
) {
  return useQuery<TranscriptResponse>({
    queryKey: ['transcript', recordingId],
    queryFn: () => getTranscript(recordingId!),
    // Fetch-uim transcriptul DOAR când înregistrarea e completă
    enabled: !!recordingId && recordingStatus === 'completed',
    // Nu reîncercăm la 404 — transcriptul poate fi temporar indisponibil
    retry: false,
  })
}
