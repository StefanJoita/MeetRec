// src/test/AdminAudit.test.tsx
// Administrare → Jurnal audit: numele resursei, resurse șterse, descriere, filtru resursă, export cu filtre.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ToastProvider } from '@/contexts/ToastContext'
import AdminPage from '@/pages/AdminPage'
import type { AuditLog, PaginatedAuditLogs } from '@/api/types'

const audit = vi.hoisted(() => ({ getAuditLogs: vi.fn(), downloadAuditLogsCsv: vi.fn() }))
vi.mock('@/api/auditLogs', () => audit)
vi.mock('@/api/users', () => ({
  getUsers: vi.fn().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20, pages: 1 }),
  createUser: vi.fn(), deleteUser: vi.fn(), updateUser: vi.fn(), resetUserPassword: vi.fn(),
}))
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'me', username: 'admin' } }) }))

function log(overrides: Partial<AuditLog>): AuditLog {
  return {
    id: crypto.randomUUID(), timestamp: '2026-10-15T09:00:00Z', user_ip: '10.0.0.5',
    user_username: 'admin', action: 'VIEW', success: true, details: {}, ...overrides,
  }
}

const LOGS: AuditLog[] = [
  log({ action: 'VIEW', resource_type: 'recording', resource_id: 'rec-1-aaaa', recording_id: 'rec-1-aaaa',
        resource_name: 'Ședința CA' }),
  log({ action: 'DELETE', resource_type: 'recording', resource_id: 'rec-2-bbbb', resource_name: 'Ședința veche',
        resource_deleted: true }),
  log({ action: 'UPDATE', resource_type: 'user', resource_id: 'usr-1-cccc', resource_name: 'Ana Pop (ana)',
        description: 'rol: operator → administrator' }),
]

function page(items: AuditLog[]): PaginatedAuditLogs {
  return { items, total: items.length, page: 1, page_size: 20, pages: 1 }
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter>
          <AdminPage />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

describe('Jurnal audit', () => {
  beforeEach(() => {
    audit.getAuditLogs.mockReset().mockResolvedValue(page(LOGS))
    audit.downloadAuditLogsCsv.mockReset()
  })

  it('arată numele resursei, linkul și resursele șterse', async () => {
    renderPage()

    const link = await screen.findByRole('link', { name: 'Ședința CA' })
    expect(link).toHaveAttribute('href', '/recordings/rec-1-aaaa')
    expect(screen.getByText('Ședința veche')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Ședința veche' })).not.toBeInTheDocument()
    expect(screen.getByText('nu mai există')).toBeInTheDocument()
    expect(screen.getByText('rol: operator → administrator')).toBeInTheDocument()
  })

  it('filtrează după resursă și exportă cu aceleași filtre', async () => {
    renderPage()
    await screen.findByText('Ședința CA')

    await userEvent.selectOptions(screen.getByLabelText('Filtru resursă'), 'user')
    await waitFor(() => expect(audit.getAuditLogs).toHaveBeenLastCalledWith(
      1, 20, { search: '', action: '', resource: 'user' }))

    await userEvent.click(screen.getByRole('button', { name: /Export CSV/ }))
    expect(audit.downloadAuditLogsCsv).toHaveBeenCalledWith({ search: '', action: '', resource: 'user' })
  })
})
