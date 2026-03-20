// frontend/src/hooks/useRecording.ts
// Hook pentru o înregistrare individuală.
// Polling automat cât timp statusul e 'queued' sau 'transcribing'.

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getRecording, deleteRecording, retryTranscription } from '@/api/recordings'
import type { RecordingResponse } from '@/api/types'

const POLLING_STATUSES = new Set(['queued', 'transcribing', 'validating'])
const POLLING_INTERVAL_MS = 5000

export function useRecording(id: string | undefined) {
  return useQuery<RecordingResponse>({
    queryKey: ['recording', id],
    queryFn: () => getRecording(id!),
    enabled: !!id,
    // Polling cât timp înregistrarea e în procesare
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && POLLING_STATUSES.has(status) ? POLLING_INTERVAL_MS : false
    },
  })
}

export function useDeleteRecording(id: string | undefined) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => deleteRecording(id!),
    onSuccess: () => {
      // Invalidăm lista după ștergere
      queryClient.invalidateQueries({ queryKey: ['recordings'] })
    },
  })
}

export function useRetryTranscription(id: string | undefined) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => retryTranscription(id!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['recording', id] })
    },
  })
}
