import { useState, useRef } from 'react'
import { Link } from 'react-router-dom'
import { Search, Clock } from 'lucide-react'
import { search as apiSearch } from '@/api/search'
import { Spinner } from '@/components/ui/Spinner'
import type { SearchResult } from '@/api/types'

export default function SearchPage() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[] | null>(null)
  const [searchTime, setSearchTime] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault()
    const q = query.trim()
    if (!q) return
    setLoading(true)
    setError('')
    try {
      const data = await apiSearch(q)
      setResults(data.results)
      setSearchTime(data.search_time_ms)
    } catch {
      setError('Eroare la căutare. Încercați din nou.')
    } finally {
      setLoading(false)
    }
  }

  function highlight(text: string, q: string): string {
    if (!q) return text
    const escaped = q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    return text.replace(new RegExp(`(${escaped})`, 'gi'), '<mark class="bg-yellow-200 rounded px-0.5">$1</mark>')
  }

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Căutare transcrieri</h1>

      <form onSubmit={handleSearch} className="flex gap-3 mb-6">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Caută în toate transcriptele..."
            className="w-full pl-10 pr-4 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <button
          type="submit"
          disabled={loading || !query.trim()}
          className="bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white px-5 py-2.5 rounded-lg text-sm font-medium transition-colors"
        >
          {loading ? <Spinner className="h-4 w-4" /> : 'Caută'}
        </button>
      </form>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-600 mb-4">
          {error}
        </div>
      )}

      {results !== null && (
        <div>
          <p className="text-sm text-gray-500 mb-4">
            {results.length === 0
              ? 'Niciun rezultat găsit.'
              : `${results.length} rezultate în ${searchTime} ms`}
          </p>

          <div className="space-y-3">
            {results.map((r) => (
              <Link
                key={`${r.recording_id}-${r.segment_id}`}
                to={`/recordings/${r.recording_id}`}
                className="block bg-white border border-gray-200 rounded-xl p-4 hover:border-blue-300 hover:shadow-sm transition-all"
              >
                <div className="flex items-start justify-between gap-3 mb-2">
                  <p className="text-sm font-medium text-gray-900">{r.recording_title}</p>
                  <div className="flex items-center gap-1 text-xs text-gray-400 shrink-0">
                    <Clock className="h-3 w-3" />
                    {new Date(r.meeting_date).toLocaleDateString('ro-RO')}
                  </div>
                </div>
                <p
                  className="text-sm text-gray-600 leading-relaxed"
                  dangerouslySetInnerHTML={{
                    __html: r.headline
                      ? r.headline.replace(/<b>/g, '<mark class="bg-yellow-200 rounded px-0.5">').replace(/<\/b>/g, '</mark>')
                      : highlight(r.text, query)
                  }}
                />
                <p className="text-xs text-blue-500 mt-2">
                  {formatTimestamp(r.start_time)} – {formatTimestamp(r.end_time)}
                </p>
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function formatTimestamp(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}
