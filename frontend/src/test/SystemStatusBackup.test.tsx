// src/test/SystemStatusBackup.test.tsx
// Administrare → Stare sistem: cardul Backup (ultima rulare, eșec, „Backup acum”).
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ToastProvider } from '@/contexts/ToastContext'
import SystemStatusPanel from '@/components/admin/SystemStatusPanel'
import type { BackupStatus, SystemStatus } from '@/api/admin'

const api = vi.hoisted(() => ({
  getSystemStatus: vi.fn(),
  runBackupNow: vi.fn(),
}))
vi.mock('@/api/admin', () => api)

function status(backup: Partial<BackupStatus>): SystemStatus {
  return {
    version: '1.2.0', whisper_model_configured: 'large-v3-turbo',
    queue: { available: true, queued: 0, processing: 0, workers: [] },
    search_index: { available: true, model: 'm', pending_segments: 0 },
    disk: null, recordings_by_status: {}, recent_failures: [],
    backup: { enabled: true, path: '/opt/meetrec-backups', last: null, requested: false, ...backup },
  }
}

function renderPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <SystemStatusPanel />
        </ToastProvider>
      </QueryClientProvider>
    </MemoryRouter>
  )
}

describe('Stare sistem → Backup', () => {
  beforeEach(() => vi.clearAllMocks())

  it('arată ultimul backup reușit și destinația', async () => {
    api.getSystemStatus.mockResolvedValue(status({
      last: { state: 'ok', trigger: 'scheduled', started_at: new Date().toISOString(),
              finished_at: new Date().toISOString(), db_bytes: 5 * 1024 ** 2,
              audio_files: 12, audio_bytes: 300 * 1024 ** 2, audio_copied: 2 },
    }))
    renderPanel()

    expect(await screen.findByText(/Ultimul backup:/)).toBeInTheDocument()
    expect(screen.getByText(/12 fișiere audio/)).toBeInTheDocument()
    expect(screen.getByText('Destinație: /opt/meetrec-backups')).toBeInTheDocument()
    expect(screen.queryByText(/Niciun backup reușit/)).not.toBeInTheDocument()
  })

  it('un backup eșuat apare cu motivul și ultimul backup reușit', async () => {
    api.getSystemStatus.mockResolvedValue(status({
      last: { state: 'failed', trigger: 'scheduled', started_at: '2026-10-29T02:00:00',
              finished_at: '2026-10-29T02:00:03', error: 'disc plin',
              last_success_at: '2026-10-27T02:01:00' },
    }))
    renderPanel()

    expect(await screen.findByText(/Ultimul backup a eșuat.*disc plin/)).toBeInTheDocument()
    expect(screen.getByText(/Ultimul backup reușit:/)).toBeInTheDocument()
    expect(screen.getByText(/Niciun backup reușit în ultimele 36 de ore/)).toBeInTheDocument()
  })

  it('„Backup acum” trimite cererea; butonul e blocat cât rulează', async () => {
    const user = userEvent.setup()
    api.getSystemStatus.mockResolvedValue(status({}))
    api.runBackupNow.mockResolvedValue(undefined)
    renderPanel()

    await user.click(await screen.findByRole('button', { name: 'Backup acum' }))

    expect(api.runBackupNow).toHaveBeenCalledOnce()
    expect(await screen.findByText(/pornește în cel mult 30 de secunde/)).toBeInTheDocument()
  })

  it('backup în curs: buton dezactivat', async () => {
    api.getSystemStatus.mockResolvedValue(status({
      last: { state: 'running', trigger: 'manual', started_at: new Date().toISOString() },
    }))
    renderPanel()

    expect(await screen.findByText('Backup în curs…')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Backup acum' })).toBeDisabled()
  })
})
