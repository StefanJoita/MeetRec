import { createContext, useContext, useState, useEffect, ReactNode } from 'react'
import { getMe, login as apiLogin, logout as apiLogout } from '@/api/auth'
import type { User } from '@/api/types'

interface AuthContextType {
  user: User | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  refreshUser: () => Promise<void>
}

export const AuthContext = createContext<AuthContextType | null>(null)

// Event emitter for logout triggered from interceptor
export const logoutEventEmitter = {
  handlers: [] as Array<() => void>,
  on(handler: () => void) {
    this.handlers.push(handler)
  },
  off(handler: () => void) {
    this.handlers = this.handlers.filter(h => h !== handler)
  },
  emit() {
    this.handlers.forEach(h => h())
  },
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  // Listen to logout event from interceptor (triggered on HTTP 401)
  useEffect(() => {
    const handleLogout = () => {
      localStorage.removeItem('access_token')
      setUser(null)
      // Redirect forțat — nu depindem de React re-render sau ProtectedRoute
      window.location.href = '/login'
    }
    logoutEventEmitter.on(handleLogout)
    return () => logoutEventEmitter.off(handleLogout)
  }, [])

  // La startup: dacă există token în localStorage, încercăm să obținem userul
  useEffect(() => {
    const token = localStorage.getItem('access_token')
    if (!token) {
      setLoading(false)
      return
    }
    getMe()
      .then(setUser)
      .catch(() => localStorage.removeItem('access_token'))
      .finally(() => setLoading(false))
  }, [])

  async function login(username: string, password: string) {
    const tokenData = await apiLogin(username, password)
    localStorage.setItem('access_token', tokenData.access_token)
    const me = await getMe()
    setUser(me)
  }

  async function logout() {
    try { await apiLogout() } catch { /* ignorăm erori de rețea la logout */ }
    localStorage.removeItem('access_token')
    setUser(null)
  }

  async function refreshUser() {
    const me = await getMe()
    setUser(me)
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth trebuie folosit în interiorul AuthProvider')
  return ctx
}
