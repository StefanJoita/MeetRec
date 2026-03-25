import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Plus, FileAudio, ChevronUp, ChevronDown, ArrowUpDown } from 'lucide-react'
import { useRecordings } from '@/hooks/useRecordings'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { EmptyState } from '@/components/ui/EmptyState'
import { SkeletonTable } from '@/components/ui/Skeleton'
import { Pagination } from '@/components/ui/Pagination'
import { PageHeader } from '@/components/ui/PageHeader'
import { useAuth } from '@/contexts/AuthContext'
import { cn } from '@/lib/cn'
import type { RecordingListItem } from '@/api/types'

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
  const { user }        = useAuth()
  const navigate        = useNavigate()
  const isParticipant   = user?.role === 'participant'
  const [page, setPage] = useState(1)
  const [status, setStatus]   = useState('')
  const [sortField, setSortField] = useState<SortField>('meeting_date')
  const [sortDir, setSortDir]     = useState<SortDir>('desc')
  const pageSize = 15

  const { data, isLoading, isError } = useRecordings({
    page,
    page_size: pageSize,
    status: status || undefined,
    sort_by: sortField,
    sort_desc: sortDir === 'desc',
  })

  function handleSort(field: SortField) {
    if (sortField === field) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortField(field)
      setSortDir('desc')
    }
  }

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

      {/* Status filter pills */}
      <div className="flex flex-wrap gap-2 mb-5">
        {STATUS_OPTIONS.map(opt => (
          <button
            key={opt.value}
            onClick={() => { setStatus(opt.value); setPage(1) }}
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
