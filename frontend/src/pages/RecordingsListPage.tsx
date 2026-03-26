import React, { useState, useCallback, useEffect } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Plus, FileAudio, ChevronUp, ChevronDown, ArrowUpDown, CheckCircle2, Loader2, Clock, Search, X } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { useRecordings } from '@/hooks/useRecordings'
import { getRecordingStats } from '@/api/recordings'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { EmptyState } from '@/components/ui/EmptyState'
import { SkeletonTable } from '@/components/ui/Skeleton'
import { Pagination } from '@/components/ui/Pagination'
import { PageHeader } from '@/components/ui/PageHeader'
import { useAuth } from '@/contexts/AuthContext'
import { cn } from '@/lib/cn'
import type { RecordingListItem } from '@/api/types'

function formatDuration(totalSeconds: number): string {
  const h = Math.floor(totalSeconds / 3600)
  const m = Math.floor((totalSeconds % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

function StatCard({
  icon, bg, label, value, raw = false,
}: {
  icon: React.ReactNode
  bg: string
  label: string
  value: number | string
  raw?: boolean
}) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-4 flex items-center gap-3 shadow-sm">
      <div className={cn('h-10 w-10 rounded-lg flex items-center justify-center shrink-0', bg)}>
        {icon}
      </div>
      <div className="min-w-0">
        <p className="text-xs text-slate-500 font-medium">{label}</p>
        <p className="text-xl font-bold text-slate-900 leading-tight">
          {raw ? value : value.toLocaleString('ro-RO')}
        </p>
      </div>
    </div>
  )
}

const STATUS_OPTIONS = [
  { value: '',             label: 'Toate' },
  { value: 'queued',       label: 'În coadă' },
  { value: 'transcribing', label: 'Transcriere' },
  { value: 'completed',    label: 'Finalizat' },
  { value: 'failed',       label: 'Eșuat' },
]

type SortField = 'meeting_date' | 'created_at' | 'title'
type SortDir   = 'asc' | 'desc'

export default function RecordingsListPage() {
  const { user }      = useAuth()
  const navigate      = useNavigate()
  const isParticipant = user?.role === 'participant'
  const pageSize      = 15

  // ── URL state ──────────────────────────────────────────────
  const [searchParams, setSearchParams] = useSearchParams()
  const page      = Math.max(1, parseInt(searchParams.get('page') ?? '1', 10))
  const status    = searchParams.get('status') ?? ''
  const search    = searchParams.get('q') ?? ''
  const sortField = (searchParams.get('sort') as SortField) ?? 'meeting_date'
  const sortDir   = (searchParams.get('dir') as SortDir) ?? 'desc'

  // Local controlled input — trimitem la URL la submit (Enter / buton)
  const [searchInput, setSearchInput] = useState(search)

  // Sincronizează input-ul când URL-ul se schimbă extern (Back/Forward)
  useEffect(() => { setSearchInput(search) }, [search])

  function setParam(key: string, value: string) {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      if (value) next.set(key, value)
      else next.delete(key)
      next.delete('page') // reset la pagina 1 la orice filtru
      return next
    }, { replace: true })
  }

  function setPage(p: number) {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      if (p > 1) next.set('page', String(p))
      else next.delete('page')
      return next
    }, { replace: true })
  }

  const handleSearchSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault()
    setParam('q', searchInput.trim())
  }, [searchInput])

  function handleSort(field: SortField) {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      if (sortField === field) {
        next.set('dir', sortDir === 'asc' ? 'desc' : 'asc')
      } else {
        next.set('sort', field)
        next.set('dir', 'desc')
      }
      next.delete('page')
      return next
    }, { replace: true })
  }

  const { data: stats } = useQuery({
    queryKey: ['recording-stats'],
    queryFn: getRecordingStats,
    staleTime: 30_000,
  })

  const { data, isLoading, isError } = useRecordings({
    page,
    page_size: pageSize,
    status: status || undefined,
    search: search || undefined,
    sort_by: sortField,
    sort_desc: sortDir === 'desc',
  })

  function SortIcon({ field }: { field: SortField }) {
    if (sortField !== field) return <ArrowUpDown className="h-3 w-3 opacity-30" />
    return sortDir === 'asc'
      ? <ChevronUp   className="h-3 w-3 text-primary-600" />
      : <ChevronDown className="h-3 w-3 text-primary-600" />
  }

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <PageHeader
        title="Înregistrări"
        subtitle={data ? `${data.total} înregistrări total` : undefined}
        actions={
          !isParticipant ? (
            <Link to="/recordings/new" className="btn-primary">
              <Plus className="h-4 w-4" />
              Înregistrare nouă
            </Link>
          ) : undefined
        }
      />

      {/* Stats cards */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
          <StatCard
            icon={<FileAudio className="h-5 w-5 text-primary-500" />}
            bg="bg-primary-50"
            label="Total"
            value={stats.total}
          />
          <StatCard
            icon={<CheckCircle2 className="h-5 w-5 text-emerald-500" />}
            bg="bg-emerald-50"
            label="Finalizate"
            value={stats.completed}
          />
          <StatCard
            icon={<Loader2 className="h-5 w-5 text-amber-500" />}
            bg="bg-amber-50"
            label="În procesare"
            value={stats.processing}
          />
          <StatCard
            icon={<Clock className="h-5 w-5 text-slate-400" />}
            bg="bg-slate-50"
            label="Ore transcrise"
            value={stats.total_duration_seconds >= 60 ? formatDuration(stats.total_duration_seconds) : '0m'}
            raw
          />
        </div>
      )}

      {/* Filters row: status pills + search */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-3 mb-5">
        <div className="flex flex-wrap gap-2">
          {STATUS_OPTIONS.map(opt => (
            <button
              key={opt.value}
              onClick={() => setParam('status', opt.value)}
              className={cn(
                'px-3.5 py-1.5 rounded-full text-sm font-medium border transition-all duration-150',
                status === opt.value
                  ? 'bg-primary-600 text-white border-primary-600 shadow-sm'
                  : 'bg-white text-slate-600 border-slate-300 hover:border-slate-400 hover:bg-slate-50'
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>

        {/* Search */}
        <form onSubmit={handleSearchSubmit} className="relative sm:ml-auto">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400 pointer-events-none" />
          <input
            type="search"
            value={searchInput}
            onChange={e => setSearchInput(e.target.value)}
            placeholder="Caută după titlu…"
            className="pl-9 pr-8 py-1.5 text-sm border border-slate-300 rounded-full bg-white focus:outline-none focus:ring-2 focus:ring-primary-400 focus:border-transparent w-52 transition-all"
          />
          {searchInput && (
            <button
              type="button"
              onClick={() => { setSearchInput(''); setParam('q', '') }}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
              aria-label="Șterge căutarea"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </form>
      </div>

      {isLoading && <SkeletonTable rows={8} cols={5} />}

      {isError && (
        <div className="card p-6 text-center text-rose-600 bg-rose-50 border-rose-200">
          Nu am putut încărca înregistrările.
        </div>
      )}

      {data && data.items.length === 0 && (
        <div className="card">
          <EmptyState
            icon={FileAudio}
            title={status ? 'Nicio înregistrare cu această stare' : 'Nicio înregistrare găsită'}
            description={
              status
                ? 'Încearcă un alt filtru.'
                : isParticipant
                  ? 'Nu ai înregistrări asignate. Contactează administratorul.'
                  : 'Adaugă prima înregistrare pentru a începe transcrierea automată.'
            }
            action={
              !status && !isParticipant ? (
                <Link to="/recordings/new" className="btn-primary">
                  <Plus className="h-4 w-4" />
                  Înregistrare nouă
                </Link>
              ) : undefined
            }
          />
        </div>
      )}

      {data && data.items.length > 0 && (
        <>
          {/* Table — md+ */}
          <div className="card overflow-hidden hidden md:block">
            <table className="min-w-full">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50/70">
                  <th
                    className="px-5 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider cursor-pointer hover:text-slate-700 select-none"
                    onClick={() => handleSort('title')}
                  >
                    <span className="inline-flex items-center gap-1.5">
                      Titlu <SortIcon field="title" />
                    </span>
                  </th>
                  <th
                    className="px-5 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider cursor-pointer hover:text-slate-700 select-none"
                    onClick={() => handleSort('meeting_date')}
                  >
                    <span className="inline-flex items-center gap-1.5">
                      Data ședinței <SortIcon field="meeting_date" />
                    </span>
                  </th>
                  <th className="px-5 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider hidden lg:table-cell">
                    Durată
                  </th>
                  <th className="px-5 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
                    Stare
                  </th>
                  <th
                    className="px-5 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider hidden lg:table-cell cursor-pointer hover:text-slate-700 select-none"
                    onClick={() => handleSort('created_at')}
                  >
                    <span className="inline-flex items-center gap-1.5">
                      Adăugat <SortIcon field="created_at" />
                    </span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.items.map((rec: RecordingListItem) => (
                  <tr
                    key={rec.id}
                    className="hover:bg-slate-50 cursor-pointer transition-colors group"
                    onClick={() => navigate(`/recordings/${rec.id}`)}
                  >
                    <td className="px-5 py-3.5">
                      <p className="text-sm font-medium text-slate-900 group-hover:text-primary-600 transition-colors leading-snug">
                        {rec.title}
                      </p>
                      <p className="text-xs text-slate-400 mt-0.5">
                        {rec.audio_format.toUpperCase()} · {rec.file_size_mb.toFixed(1)} MB
                      </p>
                    </td>
                    <td className="px-5 py-3.5 text-sm text-slate-600 whitespace-nowrap">
                      {new Date(rec.meeting_date).toLocaleDateString('ro-RO', {
                        day: 'numeric', month: 'short', year: 'numeric',
                      })}
                    </td>
                    <td className="px-5 py-3.5 text-sm text-slate-600 hidden lg:table-cell">
                      {rec.duration_formatted}
                    </td>
                    <td className="px-5 py-3.5">
                      <StatusBadge status={rec.status} />
                    </td>
                    <td className="px-5 py-3.5 text-sm text-slate-400 hidden lg:table-cell whitespace-nowrap">
                      {new Date(rec.created_at).toLocaleDateString('ro-RO', {
                        day: 'numeric', month: 'short', year: 'numeric',
                      })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Card view — mobile */}
          <div className="flex flex-col gap-2.5 md:hidden">
            {data.items.map((rec: RecordingListItem) => (
              <Link
                key={rec.id}
                to={`/recordings/${rec.id}`}
                className="card-padded hover:border-primary-200 hover:shadow-md transition-all"
              >
                <div className="flex items-start justify-between gap-2 mb-2">
                  <p className="text-sm font-medium text-slate-900 leading-snug">{rec.title}</p>
                  <StatusBadge status={rec.status} />
                </div>
                <div className="flex items-center gap-3 text-xs text-slate-400">
                  <span>
                    {new Date(rec.meeting_date).toLocaleDateString('ro-RO', {
                      day: 'numeric', month: 'short', year: 'numeric',
                    })}
                  </span>
                  <span>·</span>
                  <span>{rec.duration_formatted}</span>
                  <span>·</span>
                  <span>{rec.file_size_mb.toFixed(1)} MB</span>
                </div>
              </Link>
            ))}
          </div>

          <Pagination
            page={data.page}
            pages={data.pages}
            onPageChange={setPage}
            className="mt-4"
          />
        </>
      )}
    </div>
  )
}
