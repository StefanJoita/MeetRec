// src/test/SettingsPanel.test.tsx
// Administrare → Setări: afișare, validare, salvare, revenire la implicit, confirmare la retenție.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ToastProvider } from '@/contexts/ToastContext'
import SettingsPanel from '@/components/admin/SettingsPanel'
import type { AppSetting } from '@/api/admin'

const api = vi.hoisted(() => ({
  getSettings: vi.fn(),
  updateSetting: vi.fn(),
  resetSetting: vi.fn(),
}))
vi.mock('@/api/admin', () => api)

function setting(overrides: Partial<AppSetting>): AppSetting {
  return {
    key: 'max_job_attempts', group: 'Joburi', label: 'Încercări pe același fișier',
    description: 'desc', applies: 'La următoarea transcriere.', type: 'int',
    min: 1, max: 5, unit: null, value: 2, env_value: 2, source: 'env',
    updated_at: null, updated_by: null, ...overrides,
  }
}

const SETTINGS: AppSetting[] = [
  setting({}),
  setting({ key: 'diarization_enabled', group: 'Transcriere', label: 'Diarizare', type: 'bool',
            min: null, max: null, value: false, env_value: false }),
  setting({ key: 'retention_days', group: 'Retenție', label: 'Păstrarea înregistrărilor',
            min: 30, max: 3650, unit: 'zile', value: 730, env_value: 1095, source: 'interfata',
            updated_by: 'admin' }),
]

function renderPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <SettingsPanel />
      </ToastProvider>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  api.getSettings.mockResolvedValue(SETTINGS)
  api.updateSetting.mockResolvedValue(SETTINGS)
  api.resetSetting.mockResolvedValue(SETTINGS)
})

describe('SettingsPanel', () => {
  it('grupează setările și arată sursa valorii', async () => {
    renderPanel()

    expect(await screen.findByText('Transcriere')).toBeInTheDocument()
    expect(screen.getByText('Joburi')).toBeInTheDocument()
    expect(screen.getByText('Setat din interfață · implicit 1095 zile')).toBeInTheDocument()
    expect(screen.getAllByText('Din configurare (.env)')).toHaveLength(2)
  })

  it('salvează o valoare numerică validă', async () => {
    renderPanel()
    const input = await screen.findByLabelText('Încercări pe același fișier')

    await userEvent.clear(input)
    await userEvent.type(input, '4')
    await userEvent.click(screen.getAllByRole('button', { name: /Salvează/ })[1])

    await waitFor(() => expect(api.updateSetting).toHaveBeenCalledWith('max_job_attempts', 4))
  })

  it('valoarea în afara limitelor nu poate fi salvată', async () => {
    renderPanel()
    const input = await screen.findByLabelText('Încercări pe același fișier')

    await userEvent.clear(input)
    await userEvent.type(input, '9')

    expect(screen.getByText('Maxim 5.')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /Salvează/ })[1]).toBeDisabled()
  })

  it('comutatorul trimite valoarea booleană', async () => {
    renderPanel()

    await userEvent.click(await screen.findByRole('switch'))
    await userEvent.click(screen.getAllByRole('button', { name: /Salvează/ })[0])

    await waitFor(() => expect(api.updateSetting).toHaveBeenCalledWith('diarization_enabled', true))
  })

  it('„Implicit” resetează setarea din interfață', async () => {
    renderPanel()

    await userEvent.click(await screen.findByRole('button', { name: /Implicit/ }))

    await waitFor(() => expect(api.resetSetting).toHaveBeenCalledWith('retention_days'))
  })

  it('reducerea retenției cere confirmare înainte de salvare', async () => {
    renderPanel()
    const input = await screen.findByLabelText('Păstrarea înregistrărilor')

    await userEvent.clear(input)
    await userEvent.type(input, '365')
    await userEvent.click(screen.getAllByRole('button', { name: /Salvează/ })[2])

    expect(api.updateSetting).not.toHaveBeenCalled()
    expect(screen.getByText('Reduceți perioada de păstrare?')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Reduce perioada' }))

    await waitFor(() => expect(api.updateSetting).toHaveBeenCalledWith('retention_days', 365))
  })
})
