import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Plus, FileAudio, ChevronUp, ChevronDown } from 'lucide-react'
import { useRecordings } from '@/hooks/useRecordings'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { EmptyState } from '@/components/ui/EmptyState'
import { SkeletonTable } from '@/components/ui/Skeleton'
import { Pagination } from '@/components/ui/Pagination'
import { PageHeader } from '@/components/ui/PageHeader'
import { useAuth } from '@/contexts/AuthContext'
import type { RecordingListItem } from '@/api/types'

const STATUS_OPTIONS = [
  { value: '', label: 'Toate' },
  { value: 'queued', label: 'În coadă' },
  { value: 'transcribing', label: 'Transcriere' },
  { value: 'completed', label: 'Finalizat' },
  { value: 'failed', label: 'Eșuat' },
]

type SortField = 'meeting_date' | 'created_at' | 'title'
type SortDir = 'asc' | 'desc'

export default function RecordingsListPage() {
  const { user } = useAuth()
  const isParticipant = user?.role === 'participant'
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState('')
  const [sortField, setSortField] = useState<SortField>('meeting_date')
  const [sortDir, setSortDir] = useState<SortDir>('desc')
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
    if (sortField !== field) return <ChevronDown className="h-3 w-3 opacity-30" />
    return sortDir === 'asc'
      ? <ChevronUp className="h-3 w-3 text-blue-600" />
      : <ChevronDown className="h-3 w-3 text-blue-600" />
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

      {/* Filter chips */}
      <div className="flex flex-wrap gap-2 mb-5">
        {STATUS_OPTIONS.map(opt => (
          <button
            key={opt.value}
            onClick={() => { setStatus(opt.value); setPage(1) }}
            className={[
              'px-3 py-1.5 rounded-full text-sm font-medium border transition-colors',
              status === opt.value
                ? 'bg-blue-600 text-white border-blue-600'
                : 'bg-white text-gray-600 border-gray-300 hover:border-gray-400',
            ].join(' ')}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {isLoading && <SkeletonTable rows={8} cols={5} />}

      {isError && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-center text-red-600">
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
            <table className="min-w-full divide-y divide-gray-100">
              <thead className="bg-gray-50">
                <tr>
                  <th
                    className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100 select-none"
                    onClick={() => handleSort('title')}
                  >
                    <span className="inline-flex items-center gap-1">Titlu <SortIcon field="title" /></span>
                  </th>
                  <th
                    className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100 select-none"
                    onClick={() => handleSort('meeting_date')}
                  >
                    <span className="inline-flex items-center gap-1">Data ședinței <SortIcon field="meeting_date" /></span>
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider hidden lg:table-cell">Durată</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Stare</th>
                  <th
                    className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider hidden lg:table-cell cursor-pointer hover:bg-gray-100 select-none"
                    onClick={() => handleSort('created_at')}
                  >
                    <span className="inline-flex items-center gap-1">Adăugat <SortIcon field="created_at" /></span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {data.items.map((rec: RecordingListItem) => (
                  <tr
                    key={rec.id}
                    className="hover:bg-gray-50 transition-colors"
                  >
                    <td className="px-4 py-3">
                      <Link
                        to={`/recordings/${rec.id}`}
                        className="text-sm font-medium text-blue-600 hover:text-blue-700 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded px-1"
                      >
                        {rec.title}
                      </Link>
                      <p className="text-xs text-gray-400 mt-0.5">{rec.audio_format.toUpperCase()} · {rec.file_size_mb.toFixed(1)} MB</p>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {new Date(rec.meeting_date).toLocaleDateString('ro-RO', { day: 'numeric', month: 'short', year: 'numeric' })}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600 hidden lg:table-cell">
                      {rec.duration_formatted}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={rec.status} />
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-400 hidden lg:table-cell">
                      {new Date(rec.created_at).toLocaleDateString('ro-RO', { day: 'numeric', month: 'short', year: 'numeric' })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Card view — mobile only */}
          <div className="flex flex-col gap-3 md:hidden">
            {data.items.map((rec: RecordingListItem) => (
              <Link
                key={rec.id}
                to={`/recordings/${rec.id}`}
                className="card-padded text-left w-full hover:border-blue-200 hover:shadow-sm transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
              >
                <div className="flex items-start justify-between gap-2 mb-2">
                  <p className="text-sm font-medium text-gray-900 leading-snug">{rec.title}</p>
                  <StatusBadge status={rec.status} />
                </div>
                <div className="flex items-center gap-3 text-xs text-gray-400">
                  <span>{new Date(rec.meeting_date).toLocaleDateString('ro-RO', { day: 'numeric', month: 'short', year: 'numeric' })}</span>
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
