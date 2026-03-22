import { useState, useRef, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { Search, Clock, Loader2 } from 'lucide-react'
import DOMPurify from 'dompurify'
import { searchCombined } from '@/api/search'
import { EmptyState } from '@/components/ui/EmptyState'
import type { CombinedSearchResult, CombinedSearchResponse } from '@/api/types'

export default function SearchPage() {
  const [query, setQuery] = useState('')
  const [response, setResponse] = useState<CombinedSearchResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  // Cleanup debounce on unmount
  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [])

  const runSearch = useCallback(async (q: string) => {
    if (!q.trim()) { setResponse(null); return }
    setLoading(true)
    setError('')
    try {
      const data = await searchCombined(q.trim())
      setResponse(data)
    } catch {
      setError('Nu am putut efectua căutarea. Încearcă din nou.')
    } finally {
      setLoading(false)
    }
  }, [])

  function handleQueryChange(e: React.ChangeEvent<HTMLInputElement>) {
    const val = e.target.value
    setQuery(val)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (!val.trim()) { setResponse(null); setLoading(false); return }
    setLoading(true)
    debounceRef.current = setTimeout(() => runSearch(val), 300)
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (debounceRef.current) clearTimeout(debounceRef.current)
    runSearch(query)
  }

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <h1 className="page-title mb-6">Căutare transcrieri</h1>

      <form onSubmit={handleSubmit} className="flex gap-3 mb-6">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <input
            ref={inputRef}
            value={query}
            onChange={handleQueryChange}
            placeholder="Caută în toate transcrierile..."
            aria-label="Caută în transcrieri"
            className="w-full pl-10 pr-10 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          {loading && (
            <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-blue-500 animate-spin" />
          )}
        </div>
        <button
          type="submit"
          disabled={loading || !query.trim()}
          className="btn-primary"
        >
          Caută
        </button>
      </form>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-600 mb-4">
          {error}
        </div>
      )}

      {response === null && !loading && (
        <EmptyState
          icon={Search}
          title="Caută în toate transcrierile"
          description="Poți căuta după cuvinte cheie, subiecte discutate sau fraze exacte. Căutarea combină potrivirea exactă cu căutarea după sens."
        />
      )}

      {response !== null && (
        <div>
          <div className="flex items-center gap-4 mb-4 flex-wrap">
            <p className="text-sm text-gray-500">
              {response.results.length === 0
                ? 'Niciun rezultat găsit.'
                : `${response.results.length} rezultate găsite`}
            </p>
            {response.results.length > 0 && (
              <div className="flex gap-2">
                {response.both_count > 0 && (
                  <SourcePill source="both" count={response.both_count} />
                )}
                <SourcePill source="fts" count={response.fts_count - response.both_count} />
                <SourcePill source="semantic" count={response.semantic_count - response.both_count} />
              </div>
            )}
          </div>

          <div className="space-y-3">
            {response.results.map((r) => (
              <ResultCard key={`${r.recording_id}-${r.segment_id}`} result={r} query={query} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function ResultCard({ result: r, query }: { result: CombinedSearchResult; query: string }) {
  const rawHtml = r.headline
    ? r.headline.replace(/<b>/g, '<mark class="bg-yellow-200 rounded px-0.5">').replace(/<\/b>/g, '</mark>')
    : highlight(r.text, query)
  
  const displayHtml = DOMPurify.sanitize(rawHtml, {
    ALLOWED_TAGS: ['mark'],
    ALLOWED_ATTR: ['class'],
  })

  return (
    <Link
      to={`/recordings/${r.recording_id}`}
      className="block bg-white border border-gray-200 rounded-xl p-4 hover:border-blue-300 hover:shadow-sm transition-all"
    >
      <div className="flex items-start justify-between gap-3 mb-2">
        <p className="text-sm font-medium text-gray-900">{r.recording_title}</p>
        <div className="flex items-center gap-2 shrink-0">
          <SourceBadge source={r.source} />
          <div className="flex items-center gap-1 text-xs text-gray-400">
            <Clock className="h-3 w-3" />
            {new Date(r.meeting_date).toLocaleDateString('ro-RO')}
          </div>
        </div>
      </div>

      <p
        className="text-sm text-gray-600 leading-relaxed"
        dangerouslySetInnerHTML={{ __html: displayHtml }}
      />

      <div className="flex items-center justify-between mt-2">
        <p className="text-xs text-blue-500">
          {formatTimestamp(r.start_time)} – {formatTimestamp(r.end_time)}
        </p>
        <div className="flex gap-3 text-xs text-gray-400">
          {r.rank != null && <span>Potrivire exactă: {r.rank.toFixed(3)}</span>}
          {r.similarity != null && <span>Potrivire după sens: {(r.similarity * 100).toFixed(0)}%</span>}
        </div>
      </div>
    </Link>
  )
}

function SourceBadge({ source }: { source: CombinedSearchResult['source'] }) {
  if (source === 'both') return <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-green-100 text-green-700">Ambele</span>
  if (source === 'semantic') return <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-purple-100 text-purple-700">După sens</span>
  return <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-blue-100 text-blue-700">Exact</span>
}

function SourcePill({ source, count }: { source: CombinedSearchResult['source']; count: number }) {
  if (count <= 0) return null
  const styles = { both: 'bg-green-50 text-green-700 border-green-200', semantic: 'bg-purple-50 text-purple-700 border-purple-200', fts: 'bg-blue-50 text-blue-700 border-blue-200' }
  const labels = { both: 'Ambele', semantic: 'După sens', fts: 'Exact' }
  return <span className={`text-xs px-2 py-0.5 rounded border ${styles[source]}`}>{count} {labels[source]}</span>
}

function highlight(text: string, q: string): string {
  if (!q) return text
  const escaped = q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return text.replace(new RegExp(`(${escaped})`, 'gi'), '<mark class="bg-yellow-200 rounded px-0.5">$1</mark>')
}

function formatTimestamp(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}
