import { ReactNode, useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import {
  Mic2, Search, UploadCloud, LayoutDashboard, ShieldCheck,
  LogOut, Menu, X,
} from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'
import { cn } from '@/lib/cn'

const navItems = [
  { to: '/',       label: 'Înregistrări',    icon: LayoutDashboard },
  { to: '/search', label: 'Căutare',          icon: Search },
]

const operatorItems = [
  { to: '/recordings/new', label: 'Înregistrare nouă', icon: UploadCloud },
]

const adminItems = [
  { to: '/admin', label: 'Administrare', icon: ShieldCheck },
]

export default function AppShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [sidebarOpen, setSidebarOpen] = useState(false)

  async function handleLogout() {
    await logout()
    navigate('/login')
  }

  const initials = (user?.full_name ?? user?.username ?? '?')
    .split(' ')
    .slice(0, 2)
    .map(w => w[0]?.toUpperCase() ?? '')
    .join('')

  const roleLabel = user?.is_admin
    ? 'Administrator'
    : user?.role === 'participant'
      ? 'Participant'
      : 'Operator'

  const navLinkClass = ({ isActive }: { isActive: boolean }) =>
    cn(
      'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-150',
      isActive
        ? 'bg-primary-600 text-white shadow-sm'
        : 'text-slate-400 hover:text-white hover:bg-white/10'
    )

  const Sidebar = () => (
    <aside className="flex flex-col h-full w-64 bg-slate-900 shrink-0">
      {/* Logo */}
      <div className="flex items-center gap-3 px-5 py-[18px]">
        <div className="h-8 w-8 rounded-lg bg-primary-600 flex items-center justify-center shadow-sm shrink-0">
          <Mic2 className="h-4 w-4 text-white" />
        </div>
        <span className="font-semibold text-white tracking-tight">MeetRec</span>
      </div>

      <div className="h-px bg-white/10 mx-4" />

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
        {navItems.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            onClick={() => setSidebarOpen(false)}
            className={navLinkClass}
          >
            <Icon className="h-4 w-4 shrink-0" />
            {label}
          </NavLink>
        ))}

        {user?.role !== 'participant' && operatorItems.length > 0 && (
          <>
            <div className="pt-4 pb-1.5 px-3">
              <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-widest">
                Operare
              </p>
            </div>
            {operatorItems.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                onClick={() => setSidebarOpen(false)}
                className={navLinkClass}
              >
                <Icon className="h-4 w-4 shrink-0" />
                {label}
              </NavLink>
            ))}
          </>
        )}

        {user?.is_admin && (
          <>
            <div className="pt-4 pb-1.5 px-3">
              <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-widest">
                Admin
              </p>
            </div>
            {adminItems.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                onClick={() => setSidebarOpen(false)}
                className={navLinkClass}
              >
                <Icon className="h-4 w-4 shrink-0" />
                {label}
              </NavLink>
            ))}
          </>
        )}
      </nav>

      {/* User footer */}
      <div className="h-px bg-white/10 mx-4" />
      <div className="px-3 py-4">
        <div className="flex items-center gap-3 px-2 py-2 rounded-lg hover:bg-white/5 transition-colors">
          <div className="h-8 w-8 rounded-full bg-primary-600 flex items-center justify-center shrink-0 shadow-sm">
            <span className="text-white text-xs font-semibold">{initials}</span>
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-white truncate leading-tight">
              {user?.full_name ?? user?.username}
            </p>
            <p className="text-xs text-slate-400 truncate">{roleLabel}</p>
          </div>
          <button
            onClick={handleLogout}
            className="p-1.5 rounded-lg text-slate-500 hover:text-white hover:bg-white/10 transition-colors shrink-0"
            title="Deconectare"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>
    </aside>
  )

  return (
    <div className="flex h-screen bg-slate-50 overflow-hidden">
      {/* Sidebar desktop */}
      <div className="hidden md:flex md:flex-shrink-0">
        <Sidebar />
      </div>

      {/* Sidebar mobile — overlay */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-40 flex md:hidden">
          <div
            className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm"
            onClick={() => setSidebarOpen(false)}
          />
          <div className="relative flex flex-col w-64 z-50">
            <Sidebar />
          </div>
        </div>
      )}

      {/* Main content */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        {/* Top bar mobile */}
        <div className="md:hidden flex items-center gap-3 px-4 py-3 bg-white border-b border-slate-200 shadow-sm">
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="p-1.5 rounded-lg text-slate-600 hover:bg-slate-100 transition-colors"
          >
            {sidebarOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
          <div className="flex items-center gap-2">
            <div className="h-6 w-6 rounded-md bg-primary-600 flex items-center justify-center">
              <Mic2 className="h-3.5 w-3.5 text-white" />
            </div>
            <span className="font-semibold text-slate-900">MeetRec</span>
          </div>
        </div>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto">
          {children}
        </main>
      </div>
    </div>
  )
}
