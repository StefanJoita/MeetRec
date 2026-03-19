import { createContext, useContext, useState, useEffect, ReactNode } from 'react'
import { getMe, login as apiLogin, logout as apiLogout } from '@/api/auth'
import type { User } from '@/api/types'

interface AuthContextType {
  user: User | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextType | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

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

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth trebuie folosit în interiorul AuthProvider')
  return ctx
}
