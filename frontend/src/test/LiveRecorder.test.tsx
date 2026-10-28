// Înregistrarea din browser, cap-coadă pe pagina „Înregistrează ședința”, cu microfonul
// și Web Audio simulate: sesiune creată cu detaliile din formular, segment trimis la
// fiecare 5 minute, ultimul segment și pornirea transcrierii la oprire.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { act } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RecorderProvider } from '@/contexts/RecorderContext'
import RecordPage from '@/pages/RecordPage'

const api = vi.hoisted(() => ({
  createRecordingSession: vi.fn(),
  uploadSessionSegment: vi.fn(),
  completeRecordingSession: vi.fn(),
  refreshAccessToken: vi.fn(),
}))
vi.mock('@/api/recordingSession', () => api)
vi.mock('@/api/admin', () => ({ getUploadConfig: vi.fn().mockResolvedValue({ max_file_size_bytes: 500 * 1024 * 1024 }) }))

// ── Web Audio + microfon simulate ─────────────────────────────
let workletNode: { port: { onmessage: ((e: { data: Float32Array }) => void) | null } } | null = null
const track = { stop: vi.fn(), onended: null as null | (() => void), getSettings: () => ({ deviceId: 'mic-1' }) }

class FakeAudioWorkletNode {
  port = { onmessage: null }
  connect = vi.fn()
  constructor() { workletNode = this }
}

class FakeAudioContext {
  sampleRate = 16_000
  audioWorklet = { addModule: vi.fn().mockResolvedValue(undefined) }
  destination = {}
  createMediaStreamSource = () => ({ connect: vi.fn() })
  createGain = () => ({ gain: { value: 1 }, connect: vi.fn() })
  resume = vi.fn().mockResolvedValue(undefined)
  close = vi.fn().mockResolvedValue(undefined)
}

/** Trimite `seconds` de audio prin worklet, în blocuri ca în browser. */
function feedAudio(seconds: number) {
  const block = 16_000
  act(() => {
    for (let i = 0; i < seconds; i++) workletNode!.port.onmessage!({ data: new Float32Array(block).fill(0.2) })
  })
}

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <RecorderProvider>
          <RecordPage />
        </RecorderProvider>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  workletNode = null
  api.refreshAccessToken.mockResolvedValue(undefined)
  api.createRecordingSession.mockResolvedValue('sess-1')
  api.uploadSessionSegment.mockResolvedValue(undefined)
  api.completeRecordingSession.mockResolvedValue('sess-1')
  vi.stubGlobal('isSecureContext', true)
  vi.stubGlobal('AudioContext', FakeAudioContext)
  vi.stubGlobal('AudioWorkletNode', FakeAudioWorkletNode)
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: {
      getUserMedia: vi.fn().mockResolvedValue({ getAudioTracks: () => [track], getTracks: () => [track] }),
      enumerateDevices: vi.fn().mockResolvedValue([
        { kind: 'audioinput', deviceId: 'mic-1', label: 'Jabra Speak 750' },
        { kind: 'videoinput', deviceId: 'cam', label: 'Camera' },
      ]),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    },
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Înregistrare din browser', () => {
  it('fără HTTPS explică de ce microfonul nu e disponibil', async () => {
    vi.stubGlobal('isSecureContext', false)
    renderPage()
    expect(screen.getByText('Microfonul nu e disponibil')).toBeInTheDocument()
    expect(screen.getByText(/meetrec-ca\.crt/)).toBeInTheDocument()
  })

  it('accesul la microfon refuzat: mesaj cu ce e de făcut', async () => {
    vi.mocked(navigator.mediaDevices.getUserMedia).mockRejectedValueOnce(
      Object.assign(new Error('denied'), { name: 'NotAllowedError' }))
    renderPage()
    await userEvent.click(screen.getByRole('button', { name: /Activează microfonul/ }))
    expect(await screen.findByText(/Accesul la microfon a fost refuzat/)).toBeInTheDocument()
  })

  it('pornire → segment la 5 minute → oprire → transcriere', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.type(screen.getByLabelText('Titlu'), 'Ședința Consiliului')
    await user.type(screen.getByLabelText('Locație'), 'Sala Mare')
    await user.click(screen.getByRole('button', { name: /Activează microfonul/ }))
    // Fără nivel de clasificare înregistrarea nu pornește
    expect(await screen.findByRole('button', { name: 'Alegeți nivelul de clasificare' })).toBeDisabled()
    await user.selectOptions(screen.getByLabelText(/^Nivel de clasificare/), 'S')

    // Doar microfoanele apar în listă
    const select = await screen.findByLabelText('Microfon')
    expect(Array.from((select as HTMLSelectElement).options).map(o => o.text)).toEqual(['Jabra Speak 750'])

    await user.click(screen.getByRole('button', { name: /Pornește înregistrarea/ }))
    await screen.findByText('Se înregistrează')
    expect(api.refreshAccessToken).toHaveBeenCalled()
    expect(api.createRecordingSession).toHaveBeenCalledWith(expect.objectContaining({
      title: 'Ședința Consiliului', location: 'Sala Mare', classification: 'S',
    }))
    // Formularul dispare: detaliile au plecat la pornire
    expect(screen.queryByLabelText('Titlu')).not.toBeInTheDocument()

    feedAudio(299)
    expect(api.uploadSessionSegment).not.toHaveBeenCalled()
    feedAudio(3)                                   // trece de 5 minute
    await waitFor(() => expect(api.uploadSessionSegment).toHaveBeenCalledTimes(1))
    const [sessionId, index, wav] = api.uploadSessionSegment.mock.calls[0]
    expect([sessionId, index]).toEqual(['sess-1', 0])
    expect((wav as Blob).size).toBe(44 + 300 * 16_000 * 2)

    await user.click(screen.getByRole('button', { name: /Oprește și trimite/ }))
    await user.click(screen.getByRole('button', { name: 'Oprește' }))   // confirmare

    expect(await screen.findByText('Înregistrarea a fost trimisă la transcriere')).toBeInTheDocument()
    // Restul de 2 secunde, completat la minimul de 5 secunde cerut de Ingest
    expect(api.uploadSessionSegment).toHaveBeenCalledTimes(2)
    expect(api.uploadSessionSegment.mock.calls[1][1]).toBe(1)
    expect((api.uploadSessionSegment.mock.calls[1][2] as Blob).size).toBe(44 + 5 * 16_000 * 2)
    expect(api.completeRecordingSession).toHaveBeenCalledWith('sess-1', 2)
    expect(track.stop).toHaveBeenCalled()          // microfonul e eliberat
    expect(screen.getByRole('link', { name: 'Deschide înregistrarea' })).toHaveAttribute('href', '/recordings/sess-1')
  })

  it('serverul refuză crearea sesiunii: rămâne gata de pornire, cu mesajul serverului', async () => {
    api.createRecordingSession.mockRejectedValueOnce({ response: { status: 500, data: { detail: 'Baza de date indisponibilă' } } })
    const user = userEvent.setup()
    renderPage()
    await user.selectOptions(screen.getByLabelText(/^Nivel de clasificare/), 'N')
    await user.click(screen.getByRole('button', { name: /Activează microfonul/ }))
    await user.click(await screen.findByRole('button', { name: /Pornește înregistrarea/ }))

    expect(await screen.findByText('Baza de date indisponibilă')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Pornește înregistrarea/ })).toBeEnabled()
  })
})
