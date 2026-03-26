import { useState, useRef, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { Search, Clock, Loader2, Sparkles, SlidersHorizontal, X } from 'lucide-react'
import DOMPurify from 'dompurify'
import { searchCombined, type SearchFilters } from '@/api/search'
import { EmptyState } from '@/components/ui/EmptyState'
import { cn } from '@/lib/cn'
import type { CombinedSearchResult, CombinedSearchResponse } from '@/api/types'

const DURATION_OPTIONS = [
  { label: 'Orice durată', value: 0 },
  { label: '> 5 minute',   value: 300 },
  { label: '> 15 minute',  value: 900 },
  { label: '> 30 minute',  value: 1800 },
  { label: '> 1 oră',      value: 3600 },
]

export default function SearchPage() {
  const [query, setQuery]       = useState('')
  const [response, setResponse] = useState<CombinedSearchResponse | null>(null)
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState('')
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [filters, setFilters]   = useState<SearchFilters>({})
  const inputRef    = useRef<HTMLInputElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => { inputRef.current?.focus() }, [])
  useEffect(() => {
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [])

  const hasActiveFilters = !!(filters.date_from || filters.date_to || filters.location || filters.min_duration)

  const runSearch = useCallback(async (q: string, activeFilters: SearchFilters = {}) => {
    if (!q.trim()) { setResponse(null); return }
    setLoading(true)
    setError('')
    try {
      const data = await searchCombined(q.trim(), 20, activeFilters)
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
    debounceRef.current = setTimeout(() => runSearch(val, filters), 300)
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (debounceRef.current) clearTimeout(debounceRef.current)
    runSearch(query, filters)
  }

  function handleFilterChange(patch: Partial<SearchFilters>) {
    const next = { ...filters, ...patch }
    // Curăță valorile goale
    Object.keys(next).forEach(k => {
      const key = k as keyof SearchFilters
      if (!next[key]) delete next[key]
    })
    setFilters(next)
    if (query.trim()) runSearch(query, next)
  }

  function clearFilters() {
    setFilters({})
    if (query.trim()) runSearch(query, {})
  }

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <div className="mb-6">
        <h1 className="page-title">Căutare transcrieri</h1>
        <p className="page-subtitle">Potrivire exactă după cuvinte cheie și căutare după sens</p>
      </div>

      {/* Search bar */}
      <form onSubmit={handleSubmit} className="mb-3">
        <div className="relative">
          <Search className="absolute left-4 top-1/2 -translate-y-1/2 h-5 w-5 text-slate-400 pointer-events-none" />
          <input
            ref={inputRef}
            value={query}
            onChange={handleQueryChange}
            placeholder="Caută în toate transcrierile..."
            aria-label="Caută în transcrieri"
            className="w-full pl-12 pr-28 py-3.5 border border-slate-300 rounded-xl text-sm bg-white
                       focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500
                       shadow-sm placeholder:text-slate-400 transition"
          />
          <div className="absolute right-3 top-1/2 -translate-y-1/2 flex items-center gap-2">
            {loading && <Loader2 className="h-5 w-5 text-primary-500 animate-spin" />}
            <button
              type="button"
              onClick={() => setFiltersOpen(v => !v)}
              className={cn(
                'inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1.5 rounded-lg border transition-colors',
                filtersOpen || hasActiveFilters
                  ? 'bg-primary-50 border-primary-300 text-primary-700'
                  : 'bg-white border-slate-200 text-slate-500 hover:border-slate-300'
              )}
            >
              <SlidersHorizontal className="h-3.5 w-3.5" />
              Filtre
              {hasActiveFilters && (
                <span className="h-1.5 w-1.5 rounded-full bg-primary-500 inline-block" />
              )}
            </button>
          </div>
        </div>
      </form>

      {/* Advanced filters panel */}
      {filtersOpen && (
        <div className="mb-5 p-4 bg-slate-50 border border-slate-200 rounded-xl animate-slide-up space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {/* Date range */}
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">De la data</label>
              <input
                type="date"
                value={filters.date_from ?? ''}
                onChange={e => handleFilterChange({ date_from: e.target.value || undefined })}
                className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary-400"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Până la data</label>
              <input
                type="date"
                value={filters.date_to ?? ''}
                onChange={e => handleFilterChange({ date_to: e.target.value || undefined })}
                className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary-400"
              />
            </div>
            {/* Location */}
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Locație</label>
              <input
                type="text"
                value={filters.location ?? ''}
                onChange={e => handleFilterChange({ location: e.target.value || undefined })}
                placeholder="ex. Sala Mare"
                className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary-400"
              />
            </div>
            {/* Min duration */}
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Durată minimă</label>
              <select
                value={filters.min_duration ?? 0}
                onChange={e => handleFilterChange({ min_duration: Number(e.target.value) || undefined })}
                className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary-400"
              >
                {DURATION_OPTIONS.map(opt => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>
          </div>

          {hasActiveFilters && (
            <button
              onClick={clearFilters}
              className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-rose-600 transition-colors"
            >
              <X className="h-3.5 w-3.5" />
              Resetează filtrele
            </button>
          )}
        </div>
      )}

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
