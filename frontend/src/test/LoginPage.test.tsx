// src/test/LoginPage.test.tsx
// Teste pentru pagina de login.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import LoginPage from '@/pages/LoginPage'
import { AuthContext } from '@/contexts/AuthContext'
import type { User } from '@/api/types'

// ── Helper: wrapper cu context mock ──────────────────────────
function renderLoginPage(loginFn = vi.fn()) {
  const contextValue = {
    user: null as User | null,
    loading: false,
    login: loginFn,
    logout: vi.fn(),
  }

  return render(
    <MemoryRouter>
      <AuthContext.Provider value={contextValue}>
        <LoginPage />
      </AuthContext.Provider>
    </MemoryRouter>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('LoginPage — randare', () => {
  it('afișează titlul MeetRec', () => {
    renderLoginPage()
    expect(screen.getByText('MeetRec')).toBeInTheDocument()
  })

  it('afișează subtitlul platformei', () => {
    renderLoginPage()
    expect(screen.getByText('Sistem de transcriere ședințe')).toBeInTheDocument()
  })

  it('afișează câmpul Utilizator', () => {
    renderLoginPage()
    expect(screen.getByPlaceholderText('admin')).toBeInTheDocument()
  })

  it('afișează câmpul Parolă', () => {
    renderLoginPage()
    expect(screen.getByPlaceholderText('••••••••')).toBeInTheDocument()
  })

  it('câmpul de parolă are type="password" inițial', () => {
    renderLoginPage()
    const passwordInput = screen.getByPlaceholderText('••••••••')
    expect(passwordInput).toHaveAttribute('type', 'password')
  })

  it('afișează butonul de Conectare', () => {
    renderLoginPage()
    expect(screen.getByRole('button', { name: 'Conectare' })).toBeInTheDocument()
  })

  it('NU afișează eroarea inițial', () => {
    renderLoginPage()
    expect(screen.queryByText('Nume de utilizator sau parolă incorectă.')).not.toBeInTheDocument()
  })
})

describe('LoginPage — toggle parolă vizibilă', () => {
  it('afișează parola ca text când se apasă butonul de vizibilitate', async () => {
    renderLoginPage()
    const passwordInput = screen.getByPlaceholderText('••••••••')
    // Butonul de toggle e al doilea button (primul e Submit)
    const toggleButtons = screen.getAllByRole('button')
    const toggleBtn = toggleButtons.find(b => b.getAttribute('type') === 'button')!

    await userEvent.click(toggleBtn)

    expect(passwordInput).toHaveAttribute('type', 'text')
  })

  it('ascunde parola din nou la al doilea click', async () => {
    renderLoginPage()
    const passwordInput = screen.getByPlaceholderText('••••••••')
    const toggleButtons = screen.getAllByRole('button')
    const toggleBtn = toggleButtons.find(b => b.getAttribute('type') === 'button')!

    await userEvent.click(toggleBtn)
    await userEvent.click(toggleBtn)

    expect(passwordInput).toHaveAttribute('type', 'password')
  })
})

describe('LoginPage — submit', () => {
  it('apelează login cu datele completate', async () => {
    const loginFn = vi.fn().mockResolvedValue(undefined)
    renderLoginPage(loginFn)

    await userEvent.type(screen.getByPlaceholderText('admin'), 'testuser')
    await userEvent.type(screen.getByPlaceholderText('••••••••'), 'parola123')
    await userEvent.click(screen.getByRole('button', { name: 'Conectare' }))

    await waitFor(() => {
      expect(loginFn).toHaveBeenCalledWith('testuser', 'parola123')
    })
  })

  it('afișează eroarea când login eșuează', async () => {
    const loginFn = vi.fn().mockRejectedValue(new Error('401'))
    renderLoginPage(loginFn)

    await userEvent.type(screen.getByPlaceholderText('admin'), 'wrong')
    await userEvent.type(screen.getByPlaceholderText('••••••••'), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: 'Conectare' }))

    await waitFor(() => {
      expect(screen.getByText('Nume de utilizator sau parolă incorectă.')).toBeInTheDocument()
    })
  })

  it('butonul afișează "Se conectează..." în timp ce loading', async () => {
    // login care nu se rezolvă niciodată (pending)
    const loginFn = vi.fn().mockReturnValue(new Promise(() => {}))
    renderLoginPage(loginFn)

    await userEvent.type(screen.getByPlaceholderText('admin'), 'admin')
    await userEvent.type(screen.getByPlaceholderText('••••••••'), 'parola')
    await userEvent.click(screen.getByRole('button', { name: 'Conectare' }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Se conectează...' })).toBeInTheDocument()
    })
  })

  it('butonul e dezactivat în timp ce loading', async () => {
    const loginFn = vi.fn().mockReturnValue(new Promise(() => {}))
    renderLoginPage(loginFn)

    await userEvent.type(screen.getByPlaceholderText('admin'), 'admin')
    await userEvent.type(screen.getByPlaceholderText('••••••••'), 'parola')
    await userEvent.click(screen.getByRole('button', { name: 'Conectare' }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Se conectează...' })).toBeDisabled()
    })
  })
})
