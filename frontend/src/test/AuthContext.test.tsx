// src/test/AuthContext.test.tsx
// Teste pentru AuthProvider și hook-ul useAuth().
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AuthProvider, useAuth } from '@/contexts/AuthContext'

// ── Mock API ──────────────────────────────────────────────────
// Mockăm modulul API ca să nu facem cereri HTTP reale în teste.
vi.mock('@/api/auth', () => ({
  login: vi.fn(),
  logout: vi.fn(),
  getMe: vi.fn(),
}))

import { login as mockLogin, logout as mockLogout, getMe as mockGetMe } from '@/api/auth'

const FAKE_USER = {
  id: 'user-123',
  username: 'admin',
  email: 'admin@meetrec.ro',
  full_name: 'Administrator',
  is_active: true,
  is_admin: true,
  must_change_password: false,
}

const FAKE_TOKEN = {
  access_token: 'test.jwt.token',
  token_type: 'bearer',
  expires_in: 28800,
}

// ── Componentă helper pentru a testa hook-ul ─────────────────
function AuthDisplay() {
  const { user, loading } = useAuth()
  if (loading) return <div>loading...</div>
  if (!user) return <div>logged-out</div>
  return <div>logged-in:{user.username}</div>
}

function LoginButton() {
  const { login } = useAuth()
  return (
    <button onClick={() => login('admin', 'parola')}>
      Login
    </button>
  )
}

function LogoutButton() {
  const { logout } = useAuth()
  return <button onClick={logout}>Logout</button>
}

// ── Setup ──────────────────────────────────────────────────────
beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
})

// ── Teste ──────────────────────────────────────────────────────
describe('AuthProvider — stare inițială', () => {
  it('afișează loading=true inițial când există un token în localStorage', async () => {
    localStorage.setItem('access_token', 'some-token')
    vi.mocked(mockGetMe).mockResolvedValueOnce(FAKE_USER)

    render(
      <AuthProvider>
        <AuthDisplay />
      </AuthProvider>
    )

    // Imediat după mount — loading
    expect(screen.getByText('loading...')).toBeInTheDocument()

    // După ce getMe se rezolvă — afișează userul
    await waitFor(() => {
      expect(screen.getByText('logged-in:admin')).toBeInTheDocument()
    })
  })

  it('afișează logged-out dacă nu există token în localStorage', async () => {
    render(
      <AuthProvider>
        <AuthDisplay />
      </AuthProvider>
    )

    await waitFor(() => {
      expect(screen.getByText('logged-out')).toBeInTheDocument()
    })

    expect(mockGetMe).not.toHaveBeenCalled()
  })

  it('afișează logged-out și șterge token-ul dacă getMe eșuează', async () => {
    localStorage.setItem('access_token', 'token-expirat')
    vi.mocked(mockGetMe).mockRejectedValueOnce(new Error('401'))

    render(
      <AuthProvider>
        <AuthDisplay />
      </AuthProvider>
    )

    await waitFor(() => {
      expect(screen.getByText('logged-out')).toBeInTheDocument()
    })

    expect(localStorage.getItem('access_token')).toBeNull()
  })
})

describe('AuthProvider — login', () => {
  it('setează userul după login reușit', async () => {
    vi.mocked(mockGetMe).mockResolvedValue(FAKE_USER)
    vi.mocked(mockLogin).mockResolvedValueOnce(FAKE_TOKEN)

    render(
      <AuthProvider>
        <AuthDisplay />
        <LoginButton />
      </AuthProvider>
    )

    await waitFor(() => screen.getByText('logged-out'))

    await userEvent.click(screen.getByText('Login'))

    await waitFor(() => {
      expect(screen.getByText('logged-in:admin')).toBeInTheDocument()
    })
  })

  it('salvează token-ul în localStorage la login', async () => {
    vi.mocked(mockLogin).mockResolvedValueOnce(FAKE_TOKEN)
    vi.mocked(mockGetMe).mockResolvedValue(FAKE_USER)

    render(
      <AuthProvider>
        <AuthDisplay />
        <LoginButton />
      </AuthProvider>
    )

    await waitFor(() => screen.getByText('logged-out'))
    await userEvent.click(screen.getByText('Login'))
    await waitFor(() => screen.getByText('logged-in:admin'))

    expect(localStorage.getItem('access_token')).toBe('test.jwt.token')
  })

  it('apelează apiLogin cu username și parolă corecte', async () => {
    vi.mocked(mockLogin).mockResolvedValueOnce(FAKE_TOKEN)
    vi.mocked(mockGetMe).mockResolvedValue(FAKE_USER)

    render(
      <AuthProvider>
        <AuthDisplay />
        <LoginButton />
      </AuthProvider>
    )

    await waitFor(() => screen.getByText('logged-out'))
    await userEvent.click(screen.getByText('Login'))
    await waitFor(() => screen.getByText('logged-in:admin'))

    expect(mockLogin).toHaveBeenCalledWith('admin', 'parola')
  })
})

describe('AuthProvider — logout', () => {
  it('șterge userul și token-ul la logout', async () => {
    localStorage.setItem('access_token', 'token-valid')
    vi.mocked(mockGetMe).mockResolvedValueOnce(FAKE_USER)
    vi.mocked(mockLogout).mockResolvedValueOnce(undefined)

    render(
      <AuthProvider>
        <AuthDisplay />
        <LogoutButton />
      </AuthProvider>
    )

    await waitFor(() => screen.getByText('logged-in:admin'))

    await userEvent.click(screen.getByText('Logout'))

    await waitFor(() => {
      expect(screen.getByText('logged-out')).toBeInTheDocument()
    })

    expect(localStorage.getItem('access_token')).toBeNull()
  })

  it('efectuează logout chiar dacă apiLogout aruncă eroare (ex: rețea)', async () => {
    localStorage.setItem('access_token', 'token-valid')
    vi.mocked(mockGetMe).mockResolvedValueOnce(FAKE_USER)
    vi.mocked(mockLogout).mockRejectedValueOnce(new Error('Network error'))

    render(
      <AuthProvider>
        <AuthDisplay />
        <LogoutButton />
      </AuthProvider>
    )

    await waitFor(() => screen.getByText('logged-in:admin'))
    await userEvent.click(screen.getByText('Logout'))

    await waitFor(() => {
      expect(screen.getByText('logged-out')).toBeInTheDocument()
    })
  })
})

describe('useAuth() — eroare fără Provider', () => {
  it('aruncă eroare dacă useAuth e folosit în afara AuthProvider', () => {
    function BadComponent() {
      useAuth()
      return null
    }

    // Suprima eroarea de console din React
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    expect(() => render(<BadComponent />)).toThrow(
      'useAuth trebuie folosit în interiorul AuthProvider'
    )
    consoleError.mockRestore()
  })
})
