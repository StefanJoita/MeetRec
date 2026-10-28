// Detaliile ședinței, comune paginilor „Încarcă fișier” și „Înregistrează ședința”.
// Nivelul de clasificare e obligatoriu; restul câmpurilor sunt opționale.

import type { ClassificationCode } from '@/lib/classification'
import ClassificationPicker from '@/components/recording/ClassificationPicker'

export interface MeetingDetails {
  classification: ClassificationCode | ''
  title: string
  meetingDate: string
  location: string
  participants: string
  description: string
}

export function emptyMeetingDetails(): MeetingDetails {
  return { classification: '', title: '', meetingDate: new Date().toISOString().slice(0, 10), location: '', participants: '', description: '' }
}

/** Câmpurile completate, fără spații; cele goale lipsesc. */
export function trimmedDetails(d: MeetingDetails) {
  return {
    classification: d.classification || undefined,
    title: d.title.trim() || undefined,
    meeting_date: d.meetingDate || undefined,
    description: d.description.trim() || undefined,
    participants: d.participants.trim() || undefined,
    location: d.location.trim() || undefined,
  }
}

interface Props {
  value: MeetingDetails
  onChange: (value: MeetingDetails) => void
  disabled?: boolean
  titlePlaceholder?: string
  /** Text afișat în locul câmpului Titlu (ex. la mai multe fișiere, fiecare cu titlul lui). */
  titleNote?: string
  /** Evidențiază nivelul de clasificare cât timp nu e ales (butonul de trimitere e blocat). */
  showRequired?: boolean
}

export default function MeetingDetailsForm({ value, onChange, disabled, titlePlaceholder, titleNote, showRequired }: Props) {
  const set = (field: keyof MeetingDetails) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange({ ...value, [field]: e.target.value })

  return (
    <div className="space-y-4">
      <ClassificationPicker
        value={value.classification}
        onChange={classification => onChange({ ...value, classification })}
        disabled={disabled}
        showRequired={showRequired}
      />

      <h2 className="text-sm font-semibold text-gray-700 pt-1">Detalii ședință <span className="font-normal text-gray-400">(opțional)</span></h2>

      {titleNote ? (
        <p className="text-xs text-gray-500 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2">{titleNote}</p>
      ) : (
        <div>
          <label htmlFor="title" className="block text-xs font-medium text-gray-600 mb-1">Titlu</label>
          <input
            id="title"
            type="text"
            value={value.title}
            onChange={set('title')}
            placeholder={titlePlaceholder ?? 'ex. Ședința Consiliului Local – Ianuarie 2024'}
            disabled={disabled}
            className="input-base w-full"
          />
        </div>
      )}

      <div>
        <label htmlFor="meeting_date" className="block text-xs font-medium text-gray-600 mb-1">Data ședinței</label>
        <input
          id="meeting_date"
          type="date"
          value={value.meetingDate}
          onChange={set('meetingDate')}
          disabled={disabled}
          className="input-base w-full"
        />
      </div>

      <div>
        <label htmlFor="location" className="block text-xs font-medium text-gray-600 mb-1">Locație</label>
        <input
          id="location"
          type="text"
          value={value.location}
          onChange={set('location')}
          placeholder="ex. Sala Mare, Etaj 2"
          disabled={disabled}
          className="input-base w-full"
        />
      </div>

      <div>
        <label htmlFor="participants" className="block text-xs font-medium text-gray-600 mb-1">
          Participanți <span className="text-gray-400">(separați prin virgulă)</span>
        </label>
        <input
          id="participants"
          type="text"
          value={value.participants}
          onChange={set('participants')}
          placeholder="ex. Ion Ionescu, Maria Pop, Alexandru Dima"
          disabled={disabled}
          className="input-base w-full"
        />
      </div>

      <div>
        <label htmlFor="description" className="block text-xs font-medium text-gray-600 mb-1">Descriere</label>
        <textarea
          id="description"
          value={value.description}
          onChange={set('description')}
          placeholder="Puncte pe ordinea de zi, context, alte detalii..."
          rows={3}
          disabled={disabled}
          className="input-base w-full resize-none"
        />
      </div>
    </div>
  )
}
