import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { requestNotificationPermission } from '@/hooks/useTranscriptionNotifications'
import { useRecorder } from '@/contexts/RecorderContext'
import LiveRecorder from '@/components/recording/LiveRecorder'
import MeetingDetailsForm, { emptyMeetingDetails, trimmedDetails } from '@/components/recording/MeetingDetailsForm'
import type { SessionMetadata } from '@/api/recordingSession'
import { BetaBadge } from '@/components/ui/BetaBadge'

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
      classification: details.classification || 'N',   // butonul de pornire așteaptă alegerea
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

      <h1 className="page-title mb-1 flex items-center gap-2">Înregistrează ședința <BetaBadge className="text-xs px-2 py-1" /></h1>
      <p className="text-sm text-gray-500 mb-3">
        Înregistrați direct din browser, cu microfonul conectat la acest calculator. Puteți folosi
        aplicația în timpul înregistrării; transcrierea pornește când opriți.
      </p>
      <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-6">
        Funcție nouă, în testare. Pentru ședințele importante, păstrați și o înregistrare de rezervă
        (reportofon sau telefon), pe care o puteți încărca din „Încarcă fișier”.
      </p>

      {EDITABLE_PHASES.includes(recorder.phase) && (
        <div className="mb-6">
          <MeetingDetailsForm
            value={details}
            onChange={setDetails}
            disabled={recorder.busy}
            titlePlaceholder={`implicit: ${defaultRecordingTitle()}`}
            showRequired
          />
        </div>
      )}

      <LiveRecorder
        getMetadata={metadata}
        startBlocked={details.classification === '' ? 'Alegeți nivelul de clasificare' : undefined}
        onNewRecording={() => { recorder.reset(); setDetails(emptyMeetingDetails()) }}
      />
    </div>
  )
}
