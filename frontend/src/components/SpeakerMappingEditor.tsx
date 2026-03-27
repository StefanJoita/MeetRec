import { useMutation, useQueryClient } from '@tanstack/react-query'
import { updateSpeakerMapping } from '@/api/recordings'
import { useToast } from '@/contexts/ToastContext'
import type { ParticipantUserInfo, TranscriptSegment } from '@/api/types'

interface Props {
  recordingId: string
  segments: TranscriptSegment[]
  participants: ParticipantUserInfo[]
  speakerMapping: Record<string, string>
}

export default function SpeakerMappingEditor({ recordingId, segments, participants, speakerMapping }: Props) {
  const toast = useToast()
  const queryClient = useQueryClient()

  // Extract unique speakers from segments
  const speakers = Array.from(
    new Set(segments.map(s => s.speaker_id).filter(Boolean) as string[])
  ).sort()

  const mutation = useMutation({
    mutationFn: (mapping: Record<string, string>) =>
      updateSpeakerMapping(recordingId, mapping),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['recording', recordingId] })
      toast('Mapare vorbitori salvată.', 'success')
    },
    onError: (err: any) => {
      toast(err?.response?.data?.detail ?? 'Eroare la salvarea mapării.', 'error')
    },
  })

  if (speakers.length === 0 || participants.length === 0) return null

  function handleChange(speakerId: string, userId: string) {
    const newMapping = { ...speakerMapping, [speakerId]: userId }
    // Remove empty entries
    Object.keys(newMapping).forEach(k => { if (!newMapping[k]) delete newMapping[k] })
    mutation.mutate(newMapping)
  }

  function getSpeakerLabel(speakerId: string) {
    const match = speakerId.match(/(\d+)$/)
    return match ? `Vorbitor ${parseInt(match[1], 10) + 1}` : speakerId
  }

  return (
    <div className="space-y-2">
      {speakers.map(speakerId => (
        <div key={speakerId} className="flex items-center gap-3">
          <span className="text-sm text-gray-600 w-24 shrink-0">{getSpeakerLabel(speakerId)}</span>
          <select
            value={speakerMapping[speakerId] ?? ''}
            onChange={e => handleChange(speakerId, e.target.value)}
            disabled={mutation.isPending}
            className="flex-1 text-sm border border-gray-300 rounded-lg px-3 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">— Neatribuit —</option>
            {participants.map(p => (
              <option key={p.user_id.toString()} value={p.user_id.toString()}>
                {p.full_name ?? p.username}
              </option>
            ))}
          </select>
        </div>
      ))}
    </div>
  )
}
