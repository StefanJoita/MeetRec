import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { requestNotificationPermission } from '@/hooks/useTranscriptionNotifications'
import { useRecorder } from '@/contexts/RecorderContext'
import LiveRecorder from '@/components/recording/LiveRecorder'
import MeetingDetailsForm, { emptyMeetingDetails, trimmedDetails } from '@/components/recording/MeetingDetailsForm'
import type { SessionMetadata } from '@/api/recordingSession'

function defaultRecordingTitle(): string {
  const now = new Date()
  const two = (n: number) => String(n).padStart(2, '0')
  return `Ședință ${two(now.getDate())}.${two(now.getMonth() + 1)}.${now.getFullYear()} ${two(now.getHours())}:${two(now.getMinutes())}`
}

// Detaliile pleacă la server la pornire; după aceea formularul nu mai e afișat
const EDITABLE_PHASES = ['idle', 'requesting', 'ready', 'starting', 'error']

export default function RecordPage() {
  const navigate = useNavigate()
  const recorder = useRecorder()
  const [details, setDetails] = useState(emptyMeetingDetails)

  function metadata(): SessionMetadata {
    requestNotificationPermission()   // notificare de sistem când transcrierea e gata
    const d = trimmedDetails(details)
    return {
      ...d,
      title: d.title ?? defaultRecordingTitle(),
      meeting_date: d.meeting_date ?? new Date().toISOString().slice(0, 10),
    }
  }

  return (
    <div className="p-6 max-w-xl mx-auto">
      <button
        onClick={() => navigate(-1)}
        className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 mb-6"
      >
        <ArrowLeft className="h-4 w-4" /> Înapoi
      </button>

      <h1 className="page-title mb-1">Înregistrează ședința</h1>
      <p className="text-sm text-gray-500 mb-6">
        Înregistrați direct din browser, cu microfonul conectat la acest calculator. Puteți folosi
        aplicația în timpul înregistrării; transcrierea pornește când opriți.
      </p>

      {EDITABLE_PHASES.includes(recorder.phase) && (
        <div className="mb-6">
          <MeetingDetailsForm
            value={details}
            onChange={setDetails}
            disabled={recorder.busy}
            titlePlaceholder={`implicit: ${defaultRecordingTitle()}`}
          />
        </div>
      )}

      <LiveRecorder
        getMetadata={metadata}
        onNewRecording={() => { recorder.reset(); setDetails(emptyMeetingDetails()) }}
      />
    </div>
  )
}
