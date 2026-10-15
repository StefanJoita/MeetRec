import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { getProcessingTimes, type ProcessingItem, type ProcessingPage, type ProcessingSort } from '@/api/admin'
import { SkeletonTable } from '@/components/ui/Skeleton'
import { Pagination } from '@/components/ui/Pagination'

/** 154 → „2:34”, 3725 → „1:02:05”. */
export function formatDuration(seconds: number | null): string {
  if (seconds === null) return '—'
  const total = Math.round(seconds)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = String(total % 60).padStart(2, '0')
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`
}

function formatRatio(ratio: number | null): string {
  if (ratio === null) return '—'
  return `${ratio.toLocaleString('ro-RO', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}×`
}

function ratioClass(ratio: number | null): string {
  if (ratio === null) return 'bg-gray-100 text-gray-500'
  if (ratio <= 1) return 'bg-green-100 text-green-700'
  if (ratio <= 2) return 'bg-amber-100 text-amber-700'
  return 'bg-red-100 text-red-700'
}

function Stages({ item }: { item: ProcessingItem }) {
  const stages = ([
    ['Transcriere', item.transcription_sec],
    ['Aliniere', item.alignment_sec],
    ['Diarizare', item.diarization_sec],
  ] as const).filter(([, sec]) => sec !== null)
  if (stages.length === 0) return <span className="text-gray-400">nemăsurate</span>
  return (
    <span>
      {stages.map(([label, sec]) => `${label} ${formatDuration(sec)}`).join(' · ')}
      {item.diarization_parallel && <span className="text-gray-400"> (diarizare în paralel)</span>}
    </span>
  )
}

const TH = 'px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider'

export default function ProcessingPanel() {
  const [page, setPage] = useState(1)
  const [sort, setSort] = useState<ProcessingSort>('recent')
  const { data, isLoading, isError } = useQuery<ProcessingPage>({
    queryKey: ['admin-processing', page, sort],
    queryFn: () => getProcessingTimes(page, sort),
    placeholderData: (prev) => prev,
    retry: false,
  })

  if (isLoading) return <SkeletonTable rows={8} cols={5} />
  if (isError || !data) {
    return <div className="card-padded text-sm text-red-600">Nu am putut încărca durata procesărilor.</div>
  }

  const { summary } = data

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <p className="text-sm text-gray-600">
          {summary.count} transcrieri · {formatDuration(summary.audio_sec)} audio ·{' '}
          {formatDuration(summary.processing_sec)} procesare · raport pe total{' '}
          <span className="font-semibold text-gray-900">{formatRatio(summary.ratio)}</span>
        </p>
        <div className="flex gap-2">
          {(['recent', 'slowest'] as const).map(option => (
            <button
              key={option}
              onClick={() => { setSort(option); setPage(1) }}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium border ${
                sort === option ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-700 border-gray-300'
              }`}
            >
              {option === 'recent' ? 'Cele mai noi' : 'Cele mai lente'}
            </button>
          ))}
        </div>
      </div>

      <div className="bg-white border border-gray-200 rounded-xl overflow-x-auto mb-4">
        <table className="min-w-full divide-y divide-gray-100">
          <thead className="bg-gray-50">
            <tr>
              <th className={TH}>Înregistrare</th>
              <th className={TH}>Audio</th>
              <th className={TH}>Procesare</th>
              <th className={TH}>Raport</th>
              <th className={`${TH} hidden md:table-cell`}>Etape</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {data.items.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-12 text-center text-gray-400 text-sm">
                  Nicio transcriere finalizată încă.
                </td>
              </tr>
            )}
            {data.items.map(item => (
              <tr key={item.recording_id} className="hover:bg-gray-50 text-sm">
                <td className="px-4 py-3">
                  <Link to={`/recordings/${item.recording_id}`} className="font-medium text-blue-600 hover:underline">
                    {item.title}
                  </Link>
                  <div className="text-xs text-gray-400 mt-0.5">
                    {item.completed_at ? new Date(item.completed_at).toLocaleString('ro-RO') : '—'}
                    {item.model_used && ` · ${item.model_used}`}
                  </div>
                </td>
                <td className="px-4 py-3 whitespace-nowrap text-gray-700">{formatDuration(item.audio_sec)}</td>
                <td className="px-4 py-3 whitespace-nowrap font-medium text-gray-900">{formatDuration(item.processing_sec)}</td>
                <td className="px-4 py-3">
                  <span className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${ratioClass(item.ratio)}`}>
                    {formatRatio(item.ratio)}
                  </span>
                </td>
                <td className="px-4 py-3 text-xs text-gray-600 hidden md:table-cell"><Stages item={item} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Pagination page={data.page} pages={data.pages} total={data.total} onPageChange={setPage} />
    </div>
  )
}
