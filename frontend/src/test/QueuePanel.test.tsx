// src/test/QueuePanel.test.tsx
// Administrare → Coadă: jobul în lucru cu progresul etapelor, ordinea de așteptare,
// oprire / scoatere din coadă (cu confirmare) și mutarea în față.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ToastProvider } from '@/contexts/ToastContext'
import QueuePanel from '@/components/admin/QueuePanel'
import type { QueueItem, RunningQueueItem, TranscriptionQueue } from '@/api/admin'

const api = vi.hoisted(() => ({
  getQueue: vi.fn(),
  cancelTranscription: vi.fn(),
  prioritizeTranscription: vi.fn(),
}))
vi.mock('@/api/admin', () => api)

function waiting(id: string, title: string | null, overrides: Partial<QueueItem> = {}): QueueItem {
  return { recording_id: id, title, duration_seconds: 1800, status: 'queued',
           created_at: '2026-10-16T09:00:00Z', jobs: 1, ...overrides }
}

function running(overrides: Partial<RunningQueueItem> = {}): RunningQueueItem {
  return {
    ...waiting('rec-run', 'Ședință în lucru', { status: 'transcribing' }),
    worker_id: 'stt-worker-1', worker_alive: true,
    progress: { transcriere: 100, aliniere: 40 }, cancelling: false, cancel_requested: false,
    ...overrides,
  }
}

function queue(overrides: Partial<TranscriptionQueue> = {}): TranscriptionQueue {
  return {
    available: true,
    running: [running()],
    waiting: [waiting('rec-a', 'Prima din coadă'), waiting('rec-b', 'A doua', { jobs: 3 }), waiting('rec-c', null)],
    ...overrides,
  }
}

/** Rândurile tabelului de așteptare, după ce datele s-au încărcat (nu skeleton-ul). */
async function waitingRows() {
  await screen.findByText('Prima din coadă')
  return screen.getAllByRole('row').slice(1)
}

function renderPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter>
          <QueuePanel />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

describe('QueuePanel', () => {
  beforeEach(() => {
    api.getQueue.mockReset().mockResolvedValue(queue())
    api.cancelTranscription.mockReset().mockResolvedValue({ removed: 0, running: true })
    api.prioritizeTranscription.mockReset().mockResolvedValue(undefined)
  })

  it('arată jobul în lucru cu progresul pe etape', async () => {
    renderPanel()

    expect(await screen.findByText('Ședință în lucru')).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'Transcriere' })).toHaveAttribute('aria-valuenow', '100')
    expect(screen.getByRole('progressbar', { name: 'Aliniere' })).toHaveAttribute('aria-valuenow', '40')
    expect(screen.queryByRole('progressbar', { name: 'Diarizare' })).not.toBeInTheDocument()
  })

  it('arată coada în ordinea procesării, cu înregistrările șterse marcate', async () => {
    renderPanel()

    const rows = await waitingRows()
    expect(rows.map(r => within(r).getAllByRole('cell')[1].textContent)).toEqual([
      'Prima din coadă', 'A doua · 3 fișiere', 'Înregistrare ștearsă',
    ])
    expect(within(rows[0]).getByRole('button', { name: /Prima/ })).toBeDisabled()
  })

  it('oprește transcrierea în curs după confirmare', async () => {
    renderPanel()

    await userEvent.click(await screen.findByRole('button', { name: /Oprește/ }))
    expect(api.cancelTranscription).not.toHaveBeenCalled()
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Oprește' }))

    await waitFor(() => expect(api.cancelTranscription).toHaveBeenCalledWith('rec-run'))
    expect(await screen.findByText('Transcrierea se oprește în câteva secunde.')).toBeInTheDocument()
  })

  it('scoate o înregistrare din coadă', async () => {
    api.cancelTranscription.mockResolvedValue({ removed: 1, running: false })
    renderPanel()

    const row = (await waitingRows())[1]
    await userEvent.click(within(row).getByRole('button', { name: /Scoate/ }))
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Scoate din coadă' }))

    await waitFor(() => expect(api.cancelTranscription).toHaveBeenCalledWith('rec-b'))
    expect(await screen.findByText('Înregistrarea a fost scoasă din coadă.')).toBeInTheDocument()
  })

  it('mută o înregistrare prima în coadă', async () => {
    renderPanel()

    const row = (await waitingRows())[1]
    await userEvent.click(within(row).getByRole('button', { name: /Prima/ }))

    await waitFor(() => expect(api.prioritizeTranscription).toHaveBeenCalledWith('rec-b'))
  })

  it('arată „Se oprește…” cât timp anularea e în curs', async () => {
    api.getQueue.mockResolvedValue(queue({ running: [running({ cancelling: true })] }))
    renderPanel()

    expect(await screen.findByText('Se oprește…')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Oprește/ })).not.toBeInTheDocument()
  })

  it('afișează eroarea primită de la server', async () => {
    api.cancelTranscription.mockRejectedValue({ response: { data: { detail: 'Înregistrarea nu este în coada de transcriere.' } } })
    renderPanel()

    await userEvent.click(await screen.findByRole('button', { name: /Oprește/ }))
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Oprește' }))

    expect(await screen.findByText('Înregistrarea nu este în coada de transcriere.')).toBeInTheDocument()
  })

  it('coadă goală și Redis indisponibil', async () => {
    api.getQueue.mockResolvedValue(queue({ running: [], waiting: [] }))
    const { unmount } = renderPanel()
    expect(await screen.findByText('Nicio transcriere în curs.')).toBeInTheDocument()
    expect(screen.getByText('Coada e goală.')).toBeInTheDocument()
    unmount()

    api.getQueue.mockResolvedValue(queue({ available: false }))
    renderPanel()
    expect(await screen.findByText(/Redis nu răspunde/)).toBeInTheDocument()
  })
})
