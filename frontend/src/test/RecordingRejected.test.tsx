// Înregistrare respinsă la validare (Ingest): apare ca eșuată, cu motivul, fără
// „Reîncearcă” — nu are transcriere, deci nu există nimic de reluat.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ToastProvider } from '@/contexts/ToastContext'
import RecordingDetailPage from '@/pages/RecordingDetailPage'

const api = vi.hoisted(() => ({
  getRecording: vi.fn(),
  retryTranscription: vi.fn(),
  deleteRecording: vi.fn(),
  getRecordingParticipants: vi.fn(),
}))
vi.mock('@/api/recordings', () => api)
vi.mock('@/api/transcripts', () => ({ getTranscript: vi.fn() }))
vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'u1', username: 'op', role: 'operator', is_admin: false, is_participant: false } }),
}))

function recording(overrides: Record<string, unknown>) {
  return {
    id: 'rec-1', title: 'Voce 261006 113235', description: null, meeting_date: '2026-10-06', location: null,
    participants: null, original_filename: 'Voce 261006_113235.m4a', file_size_bytes: 70916411,
    audio_format: 'm4a', duration_seconds: null, duration_formatted: '00:00:00', file_size_mb: 67.6,
    status: 'failed', error_message: null, created_at: '2026-10-26T13:00:00Z', updated_at: '2026-10-26T13:00:00Z',
    retain_until: null, transcript: null, resolved_participants: [], speaker_mapping: {},
    ...overrides,
  }
}

function renderPage() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ToastProvider>
        <MemoryRouter initialEntries={['/recordings/rec-1']}>
          <Routes><Route path="/recordings/:id" element={<RecordingDetailPage />} /></Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  api.getRecordingParticipants.mockResolvedValue([])
})

describe('Înregistrare respinsă la validare', () => {
  it('arată motivul și trimiterea la încărcare, fără „Reîncearcă”', async () => {
    api.getRecording.mockResolvedValue(recording({
      error_message: 'Fișierul a fost respins: nu am putut determina durata înregistrării.',
    }))
    renderPage()

    expect(await screen.findByText('Fișierul a fost respins la validare și nu a fost transcris.')).toBeInTheDocument()
    expect(screen.getByText(/nu am putut determina durata/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'încărcați-l din nou' })).toHaveAttribute('href', '/recordings/upload')
    expect(screen.queryByRole('button', { name: /Reîncearcă/ })).not.toBeInTheDocument()
  })

  it('transcriere eșuată (are transcript): rămâne „Reîncearcă”', async () => {
    api.getRecording.mockResolvedValue(recording({
      error_message: 'Worker oprit', transcript: { id: 't1', status: 'failed', language: 'ro', word_count: null },
    }))
    renderPage()

    expect(await screen.findByText('Transcrierea nu a putut fi finalizată.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Reîncearcă/ })).toBeInTheDocument()
  })
})
