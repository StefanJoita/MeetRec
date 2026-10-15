import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { updateSpeakerMapping } from '@/api/recordings'
import { useToast } from '@/contexts/ToastContext'
import { speakerLabel } from '@/lib/speakers'
import type { ParticipantUserInfo, TranscriptSegment } from '@/api/types'

interface Props {
  recordingId: string
  segments: TranscriptSegment[]
  participants: ParticipantUserInfo[]
  speakerMapping: Record<string, string>
}

/**
 * Numele fiecărui vorbitor: scris liber sau ales dintre participanții cu acces
 * (atunci se salvează legătura cu contul lor).
 */
export default function SpeakerMappingEditor({ recordingId, segments, participants, speakerMapping }: Props) {
  const toast = useToast()
  const queryClient = useQueryClient()

  const speakers = Array.from(
    new Set(segments.map(s => s.speaker_id).filter(Boolean) as string[])
  ).sort()

  const nameOf = (value: string | undefined): string => {
    if (!value) return ''
    const p = participants.find(p => p.user_id.toString() === value)
    return p ? (p.full_name ?? p.username) : value
  }

  const [drafts, setDrafts] = useState<Record<string, string>>({})
  useEffect(() => {
    setDrafts(Object.fromEntries(speakers.map(s => [s, nameOf(speakerMapping[s])])))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [speakerMapping, participants, segments])

  const mutation = useMutation({
    mutationFn: (mapping: Record<string, string>) => updateSpeakerMapping(recordingId, mapping),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['recording', recordingId] })
      toast('Vorbitori salvați.', 'success')
    },
    onError: (err: any) => {
      toast(err?.response?.data?.detail ?? 'Eroare la salvarea vorbitorilor.', 'error')
    },
  })

  if (speakers.length === 0) return null

  function save(speakerId: string) {
    const typed = (drafts[speakerId] ?? '').trim()
    if (typed === nameOf(speakerMapping[speakerId])) return
    const participant = participants.find(p => (p.full_name ?? p.username).toLowerCase() === typed.toLowerCase())
    const mapping = { ...speakerMapping }
    if (!typed) delete mapping[speakerId]
    else mapping[speakerId] = participant ? participant.user_id.toString() : typed
    mutation.mutate(mapping)
  }

  const listId = `speaker-people-${recordingId}`

  return (
    <div className="space-y-2">
      <datalist id={listId}>
        {participants.map(p => <option key={p.user_id.toString()} value={p.full_name ?? p.username} />)}
      </datalist>
      {speakers.map(speakerId => (
        <div key={speakerId} className="flex items-center gap-3">
          <label htmlFor={`spk-${speakerId}`} className="text-sm text-gray-600 w-24 shrink-0">
            {speakerLabel(speakerId)}
          </label>
          <input
            id={`spk-${speakerId}`}
            list={listId}
            value={drafts[speakerId] ?? ''}
            maxLength={100}
            placeholder="Nume"
            onChange={e => setDrafts(d => ({ ...d, [speakerId]: e.target.value }))}
            onBlur={() => save(speakerId)}
            onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
            disabled={mutation.isPending}
            className="flex-1 text-sm border border-gray-300 rounded-lg px-3 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      ))}
    </div>
  )
}
