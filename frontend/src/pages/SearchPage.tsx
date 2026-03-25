import { useState, useRef, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { Search, Clock, Loader2, Sparkles } from 'lucide-react'
import DOMPurify from 'dompurify'
import { searchCombined } from '@/api/search'
import { EmptyState } from '@/components/ui/EmptyState'
import type { CombinedSearchResult, CombinedSearchResponse } from '@/api/types'

export default function SearchPage() {
  const [query, setQuery]       = useState('')
  const [response, setResponse] = useState<CombinedSearchResponse | null>(null)
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState('')
  const inputRef    = useRef<HTMLInputElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => { inputRef.current?.focus() }, [])
  useEffect(() => {
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
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
      <div className="mb-6">
        <h1 className="page-title">Căutare transcrieri</h1>
        <p className="page-subtitle">Potrivire exactă după cuvinte cheie și căutare după sens</p>
      </div>

      {/* Search bar */}
      <form onSubmit={handleSubmit} className="mb-6">
        <div className="relative">
          <Search className="absolute left-4 top-1/2 -translate-y-1/2 h-5 w-5 text-slate-400 pointer-events-none" />
          <input
            ref={inputRef}
            value={query}
            onChange={handleQueryChange}
            placeholder="Caută în toate transcrierile..."
            aria-label="Caută în transcrieri"
            className="w-full pl-12 pr-12 py-3.5 border border-slate-300 rounded-xl text-sm bg-white
                       focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500
                       shadow-sm placeholder:text-slate-400 transition"
          />
          {loading && (
            <Loader2 className="absolute right-4 top-1/2 -translate-y-1/2 h-5 w-5 text-primary-500 animate-spin pointer-events-none" />
          )}
        </div>
      </form>

      {error && (
        <div className="card p-4 text-sm text-rose-600 bg-rose-50 border-rose-200 mb-4">
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
          {/* Results summary */}
          <div className="flex items-center gap-3 mb-4 flex-wrap">
            <p className="text-sm text-slate-500 font-medium">
              {response.results.length === 0
                ? 'Niciun rezultat găsit.'
                : `${response.results.length} rezultate`}
            </p>
            {response.results.length > 0 && (
              <div className="flex gap-1.5">
                {response.both_count > 0 && (
                  <SourcePill source="both" count={response.both_count} />
                )}
                <SourcePill source="fts"      count={response.fts_count - response.both_count} />
                <SourcePill source="semantic" count={response.semantic_count - response.both_count} />
              </div>
            )}
          </div>

          <div className="space-y-2.5">
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
    ? r.headline
        .replace(/<b>/g,  '<mark class="bg-amber-100 text-amber-900 rounded px-0.5 font-medium">')
        .replace(/<\/b>/g, '</mark>')
    : highlight(r.text, query)

  const displayHtml = DOMPurify.sanitize(rawHtml, {
    ALLOWED_TAGS: ['mark'],
    ALLOWED_ATTR: ['class'],
  })

  return (
    <Link
      to={`/recordings/${r.recording_id}`}
      className="block card p-4 hover:border-primary-200 hover:shadow-md transition-all"
    >
      <div className="flex items-start justify-between gap-3 mb-2">
        <p className="text-sm font-semibold text-slate-900">{r.recording_title}</p>
        <div className="flex items-center gap-2 shrink-0">
          <SourceBadge source={r.source} />
          <div className="flex items-center gap-1 text-xs text-slate-400">
            <Clock className="h-3 w-3" />
            {new Date(r.meeting_date).toLocaleDateString('ro-RO')}
          </div>
        </div>
      </div>

      <p
        className="text-sm text-slate-600 leading-relaxed"
        dangerouslySetInnerHTML={{ __html: displayHtml }}
      />

      <div className="flex items-center justify-between mt-2.5">
        <p className="text-xs font-medium text-primary-600">
          {formatTimestamp(r.start_time)} – {formatTimestamp(r.end_time)}
        </p>
        <div className="flex gap-3 text-xs text-slate-400">
          {r.rank       != null && <span>Exactitate: {r.rank.toFixed(3)}</span>}
          {r.similarity != null && <span>Sens: {(r.similarity * 100).toFixed(0)}%</span>}
        </div>
      </div>
    </Link>
  )
}

function SourceBadge({ source }: { source: CombinedSearchResult['source'] }) {
  if (source === 'both')
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-600/20">
        <Sparkles className="h-3 w-3" /> Ambele
      </span>
    )
  if (source === 'semantic')
    return <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-violet-50 text-violet-700 ring-1 ring-inset ring-violet-600/20">După sens</span>
  return <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 ring-1 ring-inset ring-blue-600/20">Exact</span>
}

function SourcePill({ source, count }: { source: CombinedSearchResult['source']; count: number }) {
  if (count <= 0) return null
  const styles = {
    both:     'bg-emerald-50 text-emerald-700 border-emerald-200',
    semantic: 'bg-violet-50 text-violet-700 border-violet-200',
    fts:      'bg-blue-50 text-blue-700 border-blue-200',
  }
  const labels = { both: 'Ambele', semantic: 'După sens', fts: 'Exact' }
  return (
    <span className={`text-xs px-2.5 py-0.5 rounded-full border font-medium ${styles[source]}`}>
      {count} {labels[source]}
    </span>
  )
}

function highlight(text: string, q: string): string {
  if (!q) return text
  const escaped = q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return text.replace(
    new RegExp(`(${escaped})`, 'gi'),
    '<mark class="bg-amber-100 text-amber-900 rounded px-0.5 font-medium">$1</mark>'
  )
}

function formatTimestamp(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}
