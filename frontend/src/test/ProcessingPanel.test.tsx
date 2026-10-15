// src/test/ProcessingPanel.test.tsx
// Administrare → Procesări: durata totală, raportul față de audio, etapele, sortarea.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ProcessingPanel, { formatDuration } from '@/components/admin/ProcessingPanel'
import type { ProcessingItem, ProcessingPage } from '@/api/admin'

const api = vi.hoisted(() => ({ getProcessingTimes: vi.fn() }))
vi.mock('@/api/admin', () => api)

function item(overrides: Partial<ProcessingItem> = {}): ProcessingItem {
  return {
    recording_id: 'rec-1', title: 'Test YouTube', completed_at: '2026-10-14T09:00:00Z',
    model_used: 'whisper-large-v3-turbo', audio_sec: 222, processing_sec: 276, ratio: 1.24,
    transcription_sec: 154, alignment_sec: null, diarization_sec: 264.7, diarization_parallel: true,
    ...overrides,
  }
}

function page(items: ProcessingItem[]): ProcessingPage {
  return {
    items, total: items.length, page: 1, page_size: 20, pages: 1,
    summary: { count: items.length, audio_sec: 222, processing_sec: 276, ratio: 1.24 },
  }
}

function renderPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ProcessingPanel />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ProcessingPanel', () => {
  beforeEach(() => {
    api.getProcessingTimes.mockReset()
  })

  it('formatează duratele', () => {
    expect(formatDuration(154)).toBe('2:34')
    expect(formatDuration(264.7)).toBe('4:25')
    expect(formatDuration(3725)).toBe('1:02:05')
    expect(formatDuration(null)).toBe('—')
  })

  it('afișează durata, raportul și etapele fiecărei înregistrări', async () => {
    api.getProcessingTimes.mockResolvedValue(page([item()]))
    renderPanel()

    const link = await screen.findByRole('link', { name: 'Test YouTube' })
    expect(link).toHaveAttribute('href', '/recordings/rec-1')
    expect(screen.getByText('3:42')).toBeInTheDocument()
    expect(screen.getByText('4:36')).toBeInTheDocument()
    expect(screen.getAllByText('1,24×').length).toBeGreaterThan(0)
    expect(screen.getByText(/Transcriere 2:34 · Diarizare 4:25/)).toBeInTheDocument()
    expect(screen.getByText(/diarizare în paralel/)).toBeInTheDocument()
  })

  it('marchează transcrierile fără etape măsurate', async () => {
    api.getProcessingTimes.mockResolvedValue(page([item({
      transcription_sec: null, diarization_sec: null, diarization_parallel: false,
    })]))
    renderPanel()

    expect(await screen.findByText('nemăsurate')).toBeInTheDocument()
  })

  it('sortează după cele mai lente', async () => {
    api.getProcessingTimes.mockResolvedValue(page([item()]))
    renderPanel()
    await screen.findByText('Test YouTube')

    await userEvent.click(screen.getByRole('button', { name: 'Cele mai lente' }))

    await waitFor(() => expect(api.getProcessingTimes).toHaveBeenLastCalledWith(1, 'slowest'))
  })

  it('arată un mesaj când nu există transcrieri', async () => {
    api.getProcessingTimes.mockResolvedValue(page([]))
    renderPanel()

    expect(await screen.findByText('Nicio transcriere finalizată încă.')).toBeInTheDocument()
  })
})
