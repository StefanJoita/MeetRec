import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Plus, ChevronLeft, ChevronRight, FileAudio } from 'lucide-react'
import { getRecordings } from '@/api/recordings'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { Spinner } from '@/components/ui/Spinner'

const STATUS_OPTIONS = [
  { value: '', label: 'Toate statusurile' },
  { value: 'queued', label: 'În coadă' },
  { value: 'transcribing', label: 'Transcriere' },
  { value: 'completed', label: 'Finalizat' },
  { value: 'failed', label: 'Eșuat' },
]

export default function RecordingsListPage() {
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState('')
  const pageSize = 15

  const { data, isLoading, isError } = useQuery({
    queryKey: ['recordings', page, status],
    queryFn: () => getRecordings({ page, page_size: pageSize, status: status || undefined }),
  })

  return (
    <div className="p-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Înregistrări</h1>
          {data && (
            <p className="text-sm text-gray-500 mt-0.5">{data.total} înregistrări total</p>
          )}
        </div>
        <Link
          to="/recordings/new"
          className="inline-flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
        >
          <Plus className="h-4 w-4" />
          Înregistrare nouă
        </Link>
      </div>

      {/* Filtre */}
      <div className="mb-4">
        <select
          value={status}
          onChange={(e) => { setStatus(e.target.value); setPage(1) }}
          className="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {STATUS_OPTIONS.map(opt => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      </div>

      {/* Tabel */}
      {isLoading && (
        <div className="flex justify-center py-20"><Spinner className="h-8 w-8" /></div>
      )}

      {isError && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-center text-red-600">
          Eroare la încărcarea înregistrărilor.
        </div>
      )}

      {data && data.items.length === 0 && (
        <div className="bg-white border border-gray-200 rounded-xl p-12 text-center">
          <FileAudio className="h-12 w-12 text-gray-300 mx-auto mb-3" />
          <p className="text-gray-500">Nicio înregistrare găsită.</p>
          <Link to="/recordings/new" className="mt-3 inline-flex text-blue-600 text-sm hover:underline">
            Adaugă prima înregistrare
          </Link>
        </div>
      )}

      {data && data.items.length > 0 && (
        <>
          <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
            <table className="min-w-full divide-y divide-gray-100">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Titlu</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider hidden md:table-cell">Data ședinței</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider hidden lg:table-cell">Durată</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Status</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider hidden lg:table-cell">Adăugat</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {data.items.map((rec) => (
                  <tr key={rec.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3">
                      <Link to={`/recordings/${rec.id}`} className="text-sm font-medium text-blue-600 hover:text-blue-800 hover:underline">
                        {rec.title}
                      </Link>
                      <p className="text-xs text-gray-400 mt-0.5">{rec.audio_format.toUpperCase()} · {rec.file_size_mb.toFixed(1)} MB</p>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600 hidden md:table-cell">
                      {new Date(rec.meeting_date).toLocaleDateString('ro-RO')}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600 hidden lg:table-cell">
                      {rec.duration_formatted}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={rec.status} />
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-400 hidden lg:table-cell">
                      {new Date(rec.created_at).toLocaleDateString('ro-RO')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Paginare */}
          {data.pages > 1 && (
            <div className="flex items-center justify-between mt-4">
              <p className="text-sm text-gray-500">
                Pagina {data.page} din {data.pages}
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="p-2 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <button
                  onClick={() => setPage(p => Math.min(data.pages, p + 1))}
                  disabled={page === data.pages}
                  className="p-2 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
