import { FormEvent, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ShieldCheck, Activity, AlertTriangle, List, Users, UserPlus, UserX, Download, Search, X } from 'lucide-react'
import { SkeletonTable } from '@/components/ui/Skeleton'
import { Pagination } from '@/components/ui/Pagination'
import type { AuditLog, PaginatedAuditLogs, PaginatedUsers, User, UserCreate, UserRole } from '@/api/types'
import { getAuditLogs, downloadAuditLogsCsv } from '@/api/auditLogs'
import { createUser, deleteUser, getUsers, updateUser, resetUserPassword } from '@/api/users'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { useToast } from '@/contexts/ToastContext'
import { useAuth } from '@/contexts/AuthContext'

const ACTION_COLORS: Record<string, string> = {
  UPLOAD: 'bg-blue-100 text-blue-700',
  VIEW: 'bg-gray-100 text-gray-600',
  SEARCH: 'bg-purple-100 text-purple-700',
  SEMANTIC_SEARCH: 'bg-purple-100 text-purple-700',
  EXPORT: 'bg-green-100 text-green-700',
  DELETE: 'bg-red-100 text-red-700',
  TRANSCRIBE: 'bg-orange-100 text-orange-700',
  LOGIN: 'bg-indigo-100 text-indigo-700',
  RETENTION_DELETE: 'bg-red-100 text-red-700',
  CREATE: 'bg-teal-100 text-teal-700',
  UPDATE: 'bg-yellow-100 text-yellow-700',
}

const ACTION_LABELS: Record<string, string> = {
  UPLOAD: 'Încărcare',
  VIEW: 'Vizualizare',
  SEARCH: 'Căutare',
  SEMANTIC_SEARCH: 'Căutare semantică',
  EXPORT: 'Export',
  DELETE: 'Ștergere',
  TRANSCRIBE: 'Transcriere',
  LOGIN: 'Autentificare',
  RETENTION_DELETE: 'Ștergere automată',
  CREATE: 'Creare',
  UPDATE: 'Modificare',
}

const RESOURCE_LABELS: Record<string, string> = {
  recording: 'Înregistrare',
  transcript: 'Transcriere',
  user: 'Utilizator',
  search: 'Căutare',
}

function formatRelativeTime(timestamp: string): { relative: string; absolute: string } {
  const date = new Date(timestamp)
  const now = Date.now()
  const diffMs = now - date.getTime()
  const diffMin = Math.floor(diffMs / 60000)
  const diffH = Math.floor(diffMin / 60)
  const diffDays = Math.floor(diffH / 24)

  let relative: string
  if (diffMin < 1) relative = 'acum'
  else if (diffMin < 60) relative = `acum ${diffMin} min`
  else if (diffH < 24) relative = `acum ${diffH}h`
  else if (diffDays === 1) relative = 'ieri'
  else if (diffDays < 7) relative = `acum ${diffDays} zile`
  else relative = date.toLocaleDateString('ro-RO')

  const absolute = date.toLocaleString('ro-RO', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
  return { relative, absolute }
}

function getLogDescription(log: AuditLog): string | null {
  const details = log.details
  if (!details) return null
  if (log.action === 'SEARCH' || log.action === 'SEMANTIC_SEARCH') {
    const q = details.query as string | undefined
    if (q) return `"${q}"`
  }
  return null
}

export default function AdminPage() {
  const { user: currentUser } = useAuth()
  const toast = useToast()
  const queryClient = useQueryClient()

  const [activeSection, setActiveSection] = useState<'audit' | 'users'>('audit')

  const [page, setPage] = useState(1)
  const [actionFilter, setActionFilter] = useState('')
  const [auditSearch, setAuditSearch] = useState('')
  const [auditSearchInput, setAuditSearchInput] = useState('')
  const pageSize = 20

  const [userPage, setUserPage] = useState(1)
  const [userSearch, setUserSearch] = useState('')
  const [includeInactive, setIncludeInactive] = useState(false)
  const [showCreateUser, setShowCreateUser] = useState(false)
  const [showDeleteDialog, setShowDeleteDialog] = useState(false)
  const [pendingDeleteUserId, setPendingDeleteUserId] = useState<string | null>(null)
  const [resetTarget, setResetTarget] = useState<User | null>(null)
  const [resetPassword, setResetPassword] = useState('')

  const [newUserForm, setNewUserForm] = useState<UserCreate>({
    username: '',
    email: '',
    full_name: '',
    password: '',
    role: 'operator',
  })

  const { data, isLoading, isError } = useQuery<PaginatedAuditLogs>({
    queryKey: ['audit-logs', page, auditSearch, actionFilter],
    queryFn: () => getAuditLogs(page, pageSize, auditSearch || undefined, actionFilter || undefined),
    retry: false,
  })

  // Fetch recent logs for stats (max 100 — limita API)
  const { data: allData } = useQuery<PaginatedAuditLogs>({
    queryKey: ['audit-logs-all'],
    queryFn: () => getAuditLogs(1, 100),
    retry: false,
  })

  const {
    data: usersData,
    isLoading: usersLoading,
    isError: usersError,
  } = useQuery<PaginatedUsers>({
    queryKey: ['users', userPage, userSearch, includeInactive],
    queryFn: () => getUsers({ page: userPage, page_size: pageSize, search: userSearch || undefined, include_inactive: includeInactive }),
    retry: false,
    enabled: activeSection === 'users',
  })

  const createUserMutation = useMutation({
    mutationFn: (payload: UserCreate) => createUser(payload),
    onSuccess: () => {
      toast('Utilizator creat. Va trebui să-și schimbe parola la prima autentificare.', 'success')
      setShowCreateUser(false)
      setNewUserForm({ username: '', email: '', full_name: '', password: '', role: 'operator' })
      queryClient.invalidateQueries({ queryKey: ['users'] })
    },
    onError: (error: any) => {
      toast(error?.response?.data?.detail ?? 'Nu am putut crea utilizatorul.', 'error')
    },
  })

  const updateUserMutation = useMutation({
    mutationFn: ({ userId, payload }: { userId: string; payload: { role?: UserRole; is_active?: boolean } }) => updateUser(userId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      toast('Utilizator actualizat.', 'success')
    },
    onError: (error: any) => {
      toast(error?.response?.data?.detail ?? 'Nu am putut actualiza utilizatorul.', 'error')
    },
  })

  const deleteUserMutation = useMutation({
    mutationFn: (userId: string) => deleteUser(userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      toast('Utilizator șters definitiv.', 'success')
    },
    onError: (error: any) => {
      toast(error?.response?.data?.detail ?? 'Nu am putut șterge utilizatorul.', 'error')
    },
  })

  const resetPasswordMutation = useMutation({
    mutationFn: ({ userId, password }: { userId: string; password: string }) =>
      resetUserPassword(userId, password),
    onSuccess: () => {
      toast('Parola a fost resetată. Utilizatorul va fi forțat să o schimbe la login.', 'success')
      setResetTarget(null)
      setResetPassword('')
    },
    onError: (error: any) => {
      toast(error?.response?.data?.detail ?? 'Nu am putut reseta parola.', 'error')
    },
  })

  const stats = useMemo(() => {
    if (!allData) return null
    const items = allData.items
    const total = allData.total
    const sevenDaysAgo = Date.now() - 7 * 24 * 60 * 60 * 1000
    const errors = items.filter(l => !l.success && new Date(l.timestamp).getTime() > sevenDaysAgo).length
    const actionTypes = Array.from(new Set(items.map((log: AuditLog) => log.action))).sort()
    return { total, errors, actionTypes }
  }, [allData])

  const userStats = useMemo(() => {
    if (!usersData) return null
    const total = usersData.total
    const admins = usersData.items.filter(u => u.role === 'admin' && u.is_active).length
    const inactive = usersData.items.filter(u => !u.is_active).length
    return { total, admins, inactive }
  }, [usersData])

  function handleCreateUserSubmit(e: FormEvent) {
    e.preventDefault()
    createUserMutation.mutate(newUserForm)
  }

  function handleSetRole(userId: string, role: UserRole) {
    updateUserMutation.mutate({ userId, payload: { role } })
  }

  function handleToggleActive(userId: string, nextValue: boolean) {
    updateUserMutation.mutate({ userId, payload: { is_active: nextValue } })
  }

  function requestDeleteUser(userId: string) {
    setPendingDeleteUserId(userId)
    setShowDeleteDialog(true)
  }

  function confirmDeleteUser() {
    if (!pendingDeleteUserId) return
    deleteUserMutation.mutate(pendingDeleteUserId)
    setPendingDeleteUserId(null)
  }

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex items-center gap-3 mb-6">
        <div className="h-9 w-9 bg-blue-50 rounded-lg flex items-center justify-center">
          <ShieldCheck className="h-5 w-5 text-blue-600" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Administrare</h1>
          <p className="text-sm text-gray-500">Audit și management utilizatori</p>
        </div>
      </div>

      <div className="flex gap-2 mb-6">
        <button
          onClick={() => setActiveSection('audit')}
          className={`px-4 py-2 rounded-lg text-sm font-medium border ${
            activeSection === 'audit'
              ? 'bg-blue-600 text-white border-blue-600'
              : 'bg-white text-gray-700 border-gray-300'
          }`}
        >
          Jurnal audit
        </button>
        <button
          onClick={() => setActiveSection('users')}
          className={`px-4 py-2 rounded-lg text-sm font-medium border ${
            activeSection === 'users'
              ? 'bg-blue-600 text-white border-blue-600'
              : 'bg-white text-gray-700 border-gray-300'
          }`}
        >
          Utilizatori
        </button>
      </div>

      {activeSection === 'audit' && stats && (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mb-6">
          <div className="card-padded flex items-center gap-3">
            <div className="h-9 w-9 bg-blue-50 rounded-lg flex items-center justify-center shrink-0">
              <List className="h-4 w-4 text-blue-600" />
            </div>
            <div>
              <p className="text-2xl font-bold text-gray-900">{stats.total}</p>
              <p className="text-xs text-gray-500">Total intrări</p>
            </div>
          </div>
          <div className="card-padded flex items-center gap-3">
            <div className="h-9 w-9 bg-red-50 rounded-lg flex items-center justify-center shrink-0">
              <AlertTriangle className="h-4 w-4 text-red-500" />
            </div>
            <div>
              <p className="text-2xl font-bold text-gray-900">{stats.errors}</p>
              <p className="text-xs text-gray-500">Erori (7 zile)</p>
            </div>
          </div>
          <div className="card-padded flex items-center gap-3">
            <div className="h-9 w-9 bg-green-50 rounded-lg flex items-center justify-center shrink-0">
              <Activity className="h-4 w-4 text-green-600" />
            </div>
            <div>
              <p className="text-2xl font-bold text-gray-900">{stats.actionTypes.length}</p>
              <p className="text-xs text-gray-500">Tipuri acțiuni</p>
            </div>
          </div>
        </div>
      )}

      {/* Search + Action filter chips + Export */}
      {activeSection === 'audit' && stats && (
        <div className="flex flex-col gap-2 mb-4">
          <div className="flex items-center gap-2">
            <form
              className="relative flex-1 max-w-xs"
              onSubmit={e => { e.preventDefault(); setAuditSearch(auditSearchInput.trim()); setPage(1) }}
            >
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-400 pointer-events-none" />
              <input
                value={auditSearchInput}
                onChange={e => setAuditSearchInput(e.target.value)}
                placeholder="Caută după utilizator sau IP…"
                className="w-full pl-8 pr-8 py-1.5 text-sm border border-gray-300 rounded-full bg-white focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-transparent"
              />
              {auditSearchInput && (
                <button
                  type="button"
                  onClick={() => { setAuditSearchInput(''); setAuditSearch(''); setPage(1) }}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </form>
            <button
              onClick={() => downloadAuditLogsCsv(actionFilter || undefined)}
              className="ml-auto inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-300 bg-white text-xs font-medium text-slate-600 hover:bg-slate-50 transition-colors"
            >
              <Download className="h-3.5 w-3.5" />
              Export CSV
            </button>
          </div>
          {stats.actionTypes.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <button
                onClick={() => { setActionFilter(''); setPage(1) }}
                className={[
                  'px-3 py-1.5 rounded-full text-xs font-medium border transition-colors',
                  actionFilter === '' ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-600 border-gray-300 hover:border-gray-400',
                ].join(' ')}
              >
                Toate
              </button>
              {stats.actionTypes.map(action => (
                <button
                  key={action}
                  onClick={() => { setActionFilter(action); setPage(1) }}
                  className={[
                    'px-3 py-1.5 rounded-full text-xs font-medium border transition-colors',
                    actionFilter === action ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-600 border-gray-300 hover:border-gray-400',
                  ].join(' ')}
                >
                  {ACTION_LABELS[action] ?? action}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {activeSection === 'audit' && isLoading && <SkeletonTable rows={10} cols={5} />}

      {activeSection === 'audit' && isError && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-center text-red-600 text-sm">
          Nu am putut încărca jurnalul de audit. Verifică dacă ai drepturi de administrator.
        </div>
      )}

      {activeSection === 'audit' && data && (
        <>
          <div className="bg-white border border-gray-200 rounded-xl overflow-hidden mb-4">
            <table className="min-w-full divide-y divide-gray-100">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Timp</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Acțiune</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider hidden md:table-cell">Resursă</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider hidden lg:table-cell">Utilizator</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Stare</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {data.items.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-12 text-center text-gray-400 text-sm">
                      Nu există înregistrări în jurnal.
                    </td>
                  </tr>
                )}
                {data.items.map((log: AuditLog) => {
                  const { relative, absolute } = formatRelativeTime(log.timestamp)
                  const desc = getLogDescription(log)
                  const resourceLabel = log.resource_type
                    ? (RESOURCE_LABELS[log.resource_type.toLowerCase()] ?? log.resource_type)
                    : null
                  return (
                    <tr key={log.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 whitespace-nowrap" title={absolute}>
                        <span className="text-xs text-gray-700">{relative}</span>
                        <div className="text-xs text-gray-400 mt-0.5">{absolute}</div>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${ACTION_COLORS[log.action] ?? 'bg-gray-100 text-gray-600'}`}>
                          {ACTION_LABELS[log.action] ?? log.action}
                        </span>
                        {desc && (
                          <div className="text-xs text-gray-400 mt-1 max-w-[180px] truncate" title={desc}>{desc}</div>
                        )}
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-500 hidden md:table-cell">
                        {resourceLabel ?? '—'}
                        {log.resource_id && (
                          <span className="ml-1 text-gray-300" title={log.resource_id}>#{log.resource_id.slice(0, 6)}</span>
                        )}
                      </td>
                      <td className="px-4 py-3 hidden lg:table-cell">
                        {log.user_username ? (
                          <div>
                            <span className="text-xs font-medium text-gray-700">{log.user_username}</span>
                            {log.user_email && (
                              <div className="text-xs text-gray-400">{log.user_email}</div>
                            )}
                            <div className="text-xs text-gray-300 font-mono mt-0.5">{log.user_ip}</div>
                          </div>
                        ) : (
                          <span className="text-xs text-gray-400 font-mono">{log.user_ip}</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${log.success ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                          {log.success ? 'Reușit' : 'Eșuat'}
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          <Pagination
            page={data.page}
            pages={data.pages}
            total={data.total}
            onPageChange={setPage}
          />
        </>
      )}

      {activeSection === 'users' && (
        <>
          {userStats && (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mb-6">
              <div className="card-padded flex items-center gap-3">
                <div className="h-9 w-9 bg-blue-50 rounded-lg flex items-center justify-center shrink-0">
                  <Users className="h-4 w-4 text-blue-600" />
                </div>
                <div>
                  <p className="text-2xl font-bold text-gray-900">{userStats.total}</p>
                  <p className="text-xs text-gray-500">Total utilizatori</p>
                </div>
              </div>
              <div className="card-padded flex items-center gap-3">
                <div className="h-9 w-9 bg-green-50 rounded-lg flex items-center justify-center shrink-0">
                  <ShieldCheck className="h-4 w-4 text-green-600" />
                </div>
                <div>
                  <p className="text-2xl font-bold text-gray-900">{userStats.admins}</p>
                  <p className="text-xs text-gray-500">Admini activi</p>
                </div>
              </div>
              <div className="card-padded flex items-center gap-3">
                <div className="h-9 w-9 bg-red-50 rounded-lg flex items-center justify-center shrink-0">
                  <UserX className="h-4 w-4 text-red-600" />
                </div>
                <div>
                  <p className="text-2xl font-bold text-gray-900">{userStats.inactive}</p>
                  <p className="text-xs text-gray-500">Inactivi (pagină curentă)</p>
                </div>
              </div>
            </div>
          )}

          <div className="flex flex-col sm:flex-row gap-3 mb-4">
            <input
              value={userSearch}
              onChange={(e) => setUserSearch(e.target.value)}
              placeholder="Caută după utilizator sau e-mail"
              className="flex-1 px-3.5 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button
              onClick={() => setIncludeInactive(v => !v)}
              className={`px-4 py-2 rounded-lg border text-sm font-medium ${includeInactive ? 'bg-blue-50 border-blue-300 text-blue-700' : 'bg-white border-gray-300 text-gray-700'}`}
            >
              {includeInactive ? 'Ascunde inactivii' : 'Afișează inactivii'}
            </button>
            <button
              onClick={() => setShowCreateUser(v => !v)}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium"
            >
              <UserPlus className="h-4 w-4" />
              Utilizator nou
            </button>
          </div>

          {showCreateUser && (
            <form onSubmit={handleCreateUserSubmit} className="bg-white border border-gray-200 rounded-xl p-4 mb-4 grid grid-cols-1 md:grid-cols-2 gap-3">
              <input
                value={newUserForm.username}
                onChange={(e) => setNewUserForm(prev => ({ ...prev, username: e.target.value }))}
                placeholder="Nume utilizator"
                className="px-3.5 py-2.5 border border-gray-300 rounded-lg text-sm"
                required
              />
              <input
                value={newUserForm.email}
                onChange={(e) => setNewUserForm(prev => ({ ...prev, email: e.target.value }))}
                placeholder="E-mail"
                type="email"
                className="px-3.5 py-2.5 border border-gray-300 rounded-lg text-sm"
                required
              />
              <input
                value={newUserForm.full_name}
                onChange={(e) => setNewUserForm(prev => ({ ...prev, full_name: e.target.value }))}
                placeholder="Nume complet (opțional)"
                className="px-3.5 py-2.5 border border-gray-300 rounded-lg text-sm"
              />
              <input
                value={newUserForm.password}
                onChange={(e) => setNewUserForm(prev => ({ ...prev, password: e.target.value }))}
                placeholder="Parolă temporară"
                type="password"
                className="px-3.5 py-2.5 border border-gray-300 rounded-lg text-sm"
                required
                minLength={8}
              />
              <div className="md:col-span-2">
                <label className="block text-xs font-medium text-gray-600 mb-1">Rol</label>
                <select
                  value={newUserForm.role}
                  onChange={(e) => setNewUserForm(prev => ({ ...prev, role: e.target.value as UserRole }))}
                  className="w-full px-3.5 py-2.5 border border-gray-300 rounded-lg text-sm bg-white"
                >
                  <option value="operator">Operator</option>
                  <option value="participant">Participant</option>
                  <option value="admin">Administrator</option>
                </select>
              </div>
              <div className="md:col-span-2 text-xs text-gray-500">
                Utilizatorul nou va fi obligat să schimbe parola la prima autentificare.
              </div>
              <div className="md:col-span-2 flex justify-end gap-2">
                <button type="button" onClick={() => setShowCreateUser(false)} className="btn-secondary">Anulează</button>
                <button type="submit" className="btn-primary" disabled={createUserMutation.isPending}>Creează</button>
              </div>
            </form>
          )}

          {usersLoading && <SkeletonTable rows={8} cols={6} />}

          {usersError && (
            <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-center text-red-600 text-sm">
              Nu am putut încărca utilizatorii.
            </div>
          )}

          {usersData && (
            <>
              <div className="bg-white border border-gray-200 rounded-xl overflow-hidden mb-4">
                <table className="min-w-full divide-y divide-gray-100">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Utilizator</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider hidden md:table-cell">E-mail</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Rol</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Stare</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Acțiuni</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {usersData.items.length === 0 && (
                      <tr>
                        <td colSpan={5} className="px-4 py-12 text-center text-gray-400 text-sm">Niciun utilizator găsit.</td>
                      </tr>
                    )}
                    {usersData.items.map((u: User) => {
                      const isSelf = currentUser?.id === u.id
                      return (
                        <tr key={u.id} className="hover:bg-gray-50">
                          <td className="px-4 py-3 text-sm text-gray-800">
                            <div className="font-medium">{u.username}</div>
                            <div className="text-xs text-gray-400 md:hidden">{u.email}</div>
                            {u.must_change_password && (
                              <div className="text-xs text-amber-600 mt-1">Parolă temporară</div>
                            )}
                          </td>
                          <td className="px-4 py-3 text-sm text-gray-600 hidden md:table-cell">{u.email}</td>
                          <td className="px-4 py-3">
                            <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                              u.role === 'admin' ? 'bg-blue-100 text-blue-700'
                              : u.role === 'participant' ? 'bg-green-100 text-green-700'
                              : 'bg-gray-100 text-gray-600'
                            }`}>
                              {u.role === 'admin' ? 'Admin' : u.role === 'participant' ? 'Participant' : 'Operator'}
                            </span>
                          </td>
                          <td className="px-4 py-3">
                            <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${u.is_active ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                              {u.is_active ? 'Activ' : 'Inactiv'}
                            </span>
                          </td>
                          <td className="px-4 py-3">
                            <div className="flex flex-wrap gap-2">
                              <select
                                value={u.role}
                                onChange={(e) => handleSetRole(u.id, e.target.value as UserRole)}
                                disabled={isSelf || updateUserMutation.isPending}
                                className="px-2 py-1.5 rounded border border-gray-300 text-xs text-gray-700 bg-white disabled:opacity-40"
                                aria-label="Schimbă rol"
                              >
                                <option value="operator">Operator</option>
                                <option value="participant">Participant</option>
                                <option value="admin">Admin</option>
                              </select>
                              <button
                                onClick={() => handleToggleActive(u.id, !u.is_active)}
                                disabled={isSelf || updateUserMutation.isPending}
                                className="px-2.5 py-1.5 rounded border border-gray-300 text-xs text-gray-700 disabled:opacity-40"
                              >
                                {u.is_active ? 'Dezactivează' : 'Activează'}
                              </button>
                              <button
                                onClick={() => { setResetTarget(u); setResetPassword('') }}
                                className="px-2.5 py-1.5 rounded border border-amber-200 text-xs text-amber-700"
                              >
                                Resetează parola
                              </button>
                              <button
                                onClick={() => requestDeleteUser(u.id)}
                                disabled={isSelf || deleteUserMutation.isPending}
                                className="px-2.5 py-1.5 rounded border border-red-200 text-xs text-red-700 disabled:opacity-40"
                              >
                                Șterge
                              </button>
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>

              <Pagination
                page={usersData.page}
                pages={usersData.pages}
                total={usersData.total}
                onPageChange={setUserPage}
              />
            </>
          )}
        </>
      )}

      {resetTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-xl shadow-xl p-6 w-full max-w-sm mx-4">
            <h2 className="text-base font-semibold text-gray-900 mb-1">Resetează parola</h2>
            <p className="text-sm text-gray-500 mb-4">
              Setează o parolă temporară pentru <strong>{resetTarget.username}</strong>. Utilizatorul va fi obligat să o schimbe la următoarea autentificare.
            </p>
            <input
              type="password"
              value={resetPassword}
              onChange={(e) => setResetPassword(e.target.value)}
              placeholder="Parolă temporară (min. 8 caractere)"
              className="w-full px-3.5 py-2.5 border border-gray-300 rounded-lg text-sm mb-4 focus:outline-none focus:ring-2 focus:ring-blue-500"
              minLength={8}
              autoFocus
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={() => { setResetTarget(null); setResetPassword('') }}
                className="btn-secondary"
              >
                Anulează
              </button>
              <button
                onClick={() => resetPasswordMutation.mutate({ userId: resetTarget.id, password: resetPassword })}
                disabled={resetPassword.length < 8 || resetPasswordMutation.isPending}
                className="btn-primary"
              >
                Resetează
              </button>
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={showDeleteDialog}
        title="Ștergi definitiv utilizatorul?"
        description="Acțiunea este permanentă: utilizatorul va fi eliminat din baza de date."
        confirmLabel="Șterge definitiv"
        danger
        onConfirm={confirmDeleteUser}
        onClose={() => {
          setShowDeleteDialog(false)
          setPendingDeleteUserId(null)
        }}
      />
    </div>
  )
}
