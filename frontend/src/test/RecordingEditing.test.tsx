// src/test/RecordingEditing.test.tsx
// Vorbitori (nume liber sau participant), intervenții grupate în transcriere,
// editarea datelor ședinței, notificarea la finalul transcrierii.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ToastProvider } from '@/contexts/ToastContext'
import SpeakerMappingEditor from '@/components/SpeakerMappingEditor'
import TranscriptViewer from '@/components/TranscriptViewer'
import EditRecordingDialog from '@/components/recording/EditRecordingDialog'
import { useTranscriptionNotifications } from '@/hooks/useTranscriptionNotifications'
import type { RecordingResponse, TranscriptSegment } from '@/api/types'

const api = vi.hoisted(() => ({
  updateSpeakerMapping: vi.fn(),
  updateRecording: vi.fn(),
  getRecordingsActivity: vi.fn(),
}))
vi.mock('@/api/recordings', () => api)

// jsdom nu are layout: virtualizarea ar randa zero rânduri
vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getVirtualItems: () => Array.from({ length: count }, (_, i) => ({ key: i, index: i, start: i * 40 })),
    getTotalSize: () => count * 40,
    measureElement: () => {},
    scrollToIndex: () => {},
  }),
}))

function wrap(ui: React.ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider><MemoryRouter>{ui}</MemoryRouter></ToastProvider>
    </QueryClientProvider>,
  )
}

function seg(i: number, speaker: string | null, text: string): TranscriptSegment {
  return { id: `s${i}`, segment_index: i, start_time: i * 5, end_time: i * 5 + 4, text,
           confidence: null, speaker_id: speaker, language: 'ro' }
}

const SEGMENTS = [
  seg(0, 'SPEAKER_00', 'Bună ziua.'),
  seg(1, 'SPEAKER_00', 'Începem ședința.'),
  seg(2, 'SPEAKER_01', 'Mulțumesc.'),
]

const ION = { user_id: 'u-1', username: 'ion', full_name: 'Ion Popescu', email: 'i@x.ro', linked_at: '' }

describe('SpeakerMappingEditor', () => {
  beforeEach(() => { api.updateSpeakerMapping.mockReset().mockResolvedValue({}) })

  it('salvează un nume scris liber, fără participanți', async () => {
    wrap(<SpeakerMappingEditor recordingId="r1" segments={SEGMENTS} participants={[]} speakerMapping={{}} />)

    await userEvent.type(screen.getByLabelText('Vorbitor 2'), 'Ana Pop{enter}')

    await waitFor(() => expect(api.updateSpeakerMapping).toHaveBeenCalledWith('r1', { SPEAKER_01: 'Ana Pop' }))
  })

  it('numele unui participant se salvează ca legătură cu contul lui', async () => {
    wrap(<SpeakerMappingEditor recordingId="r1" segments={SEGMENTS} participants={[ION]} speakerMapping={{}} />)

    await userEvent.type(screen.getByLabelText('Vorbitor 1'), 'ion popescu{enter}')

    await waitFor(() => expect(api.updateSpeakerMapping).toHaveBeenCalledWith('r1', { SPEAKER_00: 'u-1' }))
  })

  it('golirea câmpului elimină asocierea', async () => {
    wrap(<SpeakerMappingEditor recordingId="r1" segments={SEGMENTS} participants={[ION]}
           speakerMapping={{ SPEAKER_00: 'u-1', SPEAKER_01: 'Ana Pop' }} />)

    const input = screen.getByLabelText('Vorbitor 1')
    expect(input).toHaveValue('Ion Popescu')
    await userEvent.clear(input)
    await userEvent.tab()

    await waitFor(() => expect(api.updateSpeakerMapping).toHaveBeenCalledWith('r1', { SPEAKER_01: 'Ana Pop' }))
  })
})

describe('TranscriptViewer', () => {
  it('arată vorbitorul o singură dată pe intervenție, cu eticheta „Vorbitor N”', () => {
    wrap(<TranscriptViewer segments={SEGMENTS} getCurrentTime={() => 0} onSegmentClick={() => {}}
           speakerMap={{ SPEAKER_00: 'Ion Popescu' }} />)

    expect(screen.getAllByText('Ion Popescu')).toHaveLength(1)
    expect(screen.getByText('Vorbitor 2')).toBeInTheDocument()
    expect(screen.queryByText('V2')).not.toBeInTheDocument()
  })
})

describe('EditRecordingDialog', () => {
  it('trimite datele editate', async () => {
    api.updateRecording.mockReset().mockResolvedValue({})
    const recording = {
      id: 'r1', title: 'Ședința CA', meeting_date: '2026-10-01', location: null, description: null,
      participants: ['Ion'],
    } as unknown as RecordingResponse
    const onClose = vi.fn()
    wrap(<EditRecordingDialog recording={recording} onClose={onClose} />)

    const title = screen.getByLabelText('Titlu')
    await userEvent.clear(title)
    await userEvent.type(title, 'Ședința CA — octombrie')
    await userEvent.type(screen.getByLabelText('Participanți (separați prin virgulă)'), ', Ana ,')
    await userEvent.click(screen.getByRole('button', { name: 'Salvează' }))

    await waitFor(() => expect(api.updateRecording).toHaveBeenCalledWith('r1', {
      title: 'Ședința CA — octombrie', meeting_date: '2026-10-01', location: '', description: '',
      participants: ['Ion', 'Ana'],
    }))
    expect(onClose).toHaveBeenCalled()
  })
})

describe('useTranscriptionNotifications', () => {
  function Probe() { useTranscriptionNotifications(); return null }

  beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }) })
  afterEach(() => { vi.useRealTimers() })

  it('anunță doar transcrierile văzute în curs', async () => {
    api.getRecordingsActivity.mockReset()
      .mockResolvedValueOnce({ server_time: 't1', in_progress: [{ id: 'r1', title: 'Ședința CA', status: 'transcribing' }], finished: [] })
      .mockResolvedValueOnce({ server_time: 't2', in_progress: [], finished: [
        { id: 'r1', title: 'Ședința CA', status: 'completed' },
        { id: 'r9', title: 'Editată doar', status: 'completed' },     // nevăzută în curs: fără notificare
      ] })
    wrap(<Probe />)
    await waitFor(() => expect(api.getRecordingsActivity).toHaveBeenCalledWith(null))

    await act(async () => { vi.advanceTimersByTime(20_000) })

    expect(await screen.findByText('Transcrierea „Ședința CA” este gata.')).toBeInTheDocument()
    expect(screen.queryByText(/Editată doar/)).not.toBeInTheDocument()
    expect(api.getRecordingsActivity).toHaveBeenLastCalledWith('t1')
  })
})
