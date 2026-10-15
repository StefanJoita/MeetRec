import { FormEvent, useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { updateRecording } from '@/api/recordings'
import { useToast } from '@/contexts/ToastContext'
import type { RecordingResponse as Recording } from '@/api/types'

interface Props {
  recording: Recording
  onClose: () => void
}

const INPUT = 'w-full px-3 py-2 text-sm border border-gray-300 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500'

/** Titlul, data, locația, descrierea și participanții ședinței (operator / admin). */
export default function EditRecordingDialog({ recording, onClose }: Props) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [form, setForm] = useState({
    title: recording.title,
    meeting_date: recording.meeting_date.slice(0, 10),
    location: recording.location ?? '',
    description: recording.description ?? '',
    participants: (recording.participants ?? []).join(', '),
  })

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const mutation = useMutation({
    mutationFn: () => updateRecording(recording.id, {
      title: form.title.trim(),
      meeting_date: form.meeting_date,
      location: form.location.trim(),
      description: form.description.trim(),
      participants: form.participants.split(',').map(p => p.trim()).filter(Boolean),
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['recording', recording.id] })
      queryClient.invalidateQueries({ queryKey: ['recordings'] })
      toast('Datele ședinței au fost salvate.', 'success')
      onClose()
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail
      toast(typeof detail === 'string' ? detail : 'Datele nu au putut fi salvate.', 'error')
    },
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    mutation.mutate()
  }

  const set = (key: keyof typeof form) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setForm(f => ({ ...f, [key]: e.target.value }))

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <form
        onSubmit={submit}
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="edit-recording-title"
        className="bg-white rounded-xl shadow-xl p-6 w-full max-w-lg mx-4 space-y-3"
      >
        <h2 id="edit-recording-title" className="text-base font-semibold text-gray-900 mb-1">Datele ședinței</h2>

        <div>
          <label htmlFor="er-title" className="block text-xs font-medium text-gray-600 mb-1">Titlu</label>
          <input id="er-title" required minLength={3} maxLength={500} value={form.title} onChange={set('title')} className={INPUT} autoFocus />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor="er-date" className="block text-xs font-medium text-gray-600 mb-1">Data ședinței</label>
            <input id="er-date" type="date" required value={form.meeting_date} onChange={set('meeting_date')} className={INPUT} />
          </div>
          <div>
            <label htmlFor="er-location" className="block text-xs font-medium text-gray-600 mb-1">Locație</label>
            <input id="er-location" value={form.location} onChange={set('location')} className={INPUT} />
          </div>
        </div>
        <div>
          <label htmlFor="er-participants" className="block text-xs font-medium text-gray-600 mb-1">Participanți (separați prin virgulă)</label>
          <input id="er-participants" value={form.participants} onChange={set('participants')} className={INPUT} />
        </div>
        <div>
          <label htmlFor="er-description" className="block text-xs font-medium text-gray-600 mb-1">Descriere</label>
          <textarea id="er-description" rows={3} value={form.description} onChange={set('description')} className={INPUT} />
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="btn-secondary">Renunță</button>
          <button type="submit" disabled={mutation.isPending || form.title.trim().length < 3} className="btn-primary">
            {mutation.isPending ? 'Se salvează...' : 'Salvează'}
          </button>
        </div>
      </form>
    </div>
  )
}
