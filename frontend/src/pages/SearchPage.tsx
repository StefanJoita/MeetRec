import { useState, useRef, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Search, Clock, Loader2, Sparkles, SlidersHorizontal, X, FileText, AlertTriangle, User } from 'lucide-react'
import DOMPurify from 'dompurify'
import { getSearchSpeakers, searchCombined, type SearchFilters } from '@/api/search'
import { EmptyState } from '@/components/ui/EmptyState'
import { Pagination } from '@/components/ui/Pagination'
import { cn } from '@/lib/cn'
import type { CombinedSearchResult, CombinedSearchResponse, RecordingMatch, SearchGroup } from '@/api/types'

const DURATION_OPTIONS = [
  { label: 'Orice durată', value: 0 },
  { label: '> 5 minute',   value: 300 },
  { label: '> 15 minute',  value: 900 },
  { label: '> 30 minute',  value: 1800 },
  { label: '> 1 oră',      value: 3600 },
]

const MARK = '<mark class="bg-amber-100 text-amber-900 rounded px-0.5 font-medium">'

export default function SearchPage() {
  const [query, setQuery]       = useState('')
  const [submitted, setSubmitted] = useState('')        // căutarea afișată (Enter / buton)
  const [page, setPage]         = useState(1)
  const [response, setResponse] = useState<CombinedSearchResponse | null>(null)
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState('')
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [filters, setFilters]   = useState<SearchFilters>({})
  const inputRef = useRef<HTMLInputElement>(null)

  const { data: speakers = [] } = useQuery({
    queryKey: ['search-speakers'],
    queryFn: getSearchSpeakers,
    retry: false,
    staleTime: 5 * 60_000,
  })

  useEffect(() => { inputRef.current?.focus() }, [])

  const hasActiveFilters = !!(filters.date_from || filters.date_to || filters.location || filters.min_duration || filters.speaker)

  // Căutarea pornește la Enter / buton, nu la fiecare tastă: fiecare căutare
  // ajunge în jurnalul de audit, iar căutarea după sens e costisitoare.
  const runSearch = useCallback(async (q: string, activeFilters: SearchFilters, targetPage = 1) => {
    if (q.trim().length < 2) { setResponse(null); setSubmitted(''); return }
    setLoading(true)
    setError('')
    try {
      const data = await searchCombined(q.trim(), targetPage, activeFilters)
      setResponse(data)
      setSubmitted(q.trim())
      setPage(targetPage)
    } catch {
      setError('Nu am putut efectua căutarea. Încearcă din nou.')
    } finally {
      setLoading(false)
    }
  }, [])

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    runSearch(query, filters)
  }

  function handleFilterChange(patch: Partial<SearchFilters>) {
    const next = { ...filters, ...patch }
    Object.keys(next).forEach(k => {
      const key = k as keyof SearchFilters
      if (!next[key]) delete next[key]
    })
    setFilters(next)
    if (submitted) runSearch(submitted, next)
  }

  function clearFilters() {
    setFilters({})
    if (submitted) runSearch(submitted, {})
  }

  function changePage(p: number) {
    runSearch(submitted, filters, p)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const nothingFound = response !== null && response.groups.length === 0 && response.recordings.length === 0

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <div className="mb-6">
        <h1 className="page-title">Căutare transcrieri</h1>
      </div>

      {/* Search bar */}
      <form onSubmit={handleSubmit} className="mb-4">
        <div className="relative">
          <Search className="absolute left-4 top-1/2 -translate-y-1/2 h-5 w-5 text-slate-400 pointer-events-none" />
          <input
            ref={inputRef}
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Caută în toate transcrierile și apasă Enter..."
            aria-label="Caută în transcrieri"
            className="w-full pl-12 pr-44 py-3.5 border border-slate-300 rounded-xl text-sm bg-white
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
              {hasActiveFilters && <span className="h-1.5 w-1.5 rounded-full bg-primary-500 inline-block" />}
            </button>
            <button
              type="submit"
              disabled={query.trim().length < 2 || loading}
              className="text-xs font-medium px-3 py-1.5 rounded-lg bg-primary-600 text-white hover:bg-primary-700 disabled:opacity-50"
            >
              Caută
            </button>
          </div>
        </div>
      </form>

      {/* Advanced filters panel */}
      {filtersOpen && (
        <div className="mb-5 p-4 bg-slate-50 border border-slate-200 rounded-xl animate-slide-up space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label htmlFor="f-from" className="block text-xs font-medium text-slate-600 mb-1">De la data</label>
              <input id="f-from" type="date" value={filters.date_from ?? ''}
                onChange={e => handleFilterChange({ date_from: e.target.value || undefined })}
                className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary-400" />
            </div>
            <div>
              <label htmlFor="f-to" className="block text-xs font-medium text-slate-600 mb-1">Până la data</label>
              <input id="f-to" type="date" value={filters.date_to ?? ''}
                onChange={e => handleFilterChange({ date_to: e.target.value || undefined })}
                className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary-400" />
            </div>
            <div>
              <label htmlFor="f-location" className="block text-xs font-medium text-slate-600 mb-1">Locație</label>
              <input id="f-location" type="text" value={filters.location ?? ''}
                onChange={e => setFilters(f => ({ ...f, location: e.target.value || undefined }))}
                onBlur={() => handleFilterChange({})}
                placeholder="ex. Sala Mare"
                className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary-400" />
            </div>
            <div>
              <label htmlFor="f-duration" className="block text-xs font-medium text-slate-600 mb-1">Durată minimă</label>
              <select id="f-duration" value={filters.min_duration ?? 0}
                onChange={e => handleFilterChange({ min_duration: Number(e.target.value) || undefined })}
                className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary-400">
                {DURATION_OPTIONS.map(opt => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
              </select>
            </div>
            {speakers.length > 0 && (
              <div className="sm:col-span-2">
                <label htmlFor="f-speaker" className="block text-xs font-medium text-slate-600 mb-1">Vorbitor</label>
                <select id="f-speaker" value={filters.speaker ?? ''}
                  onChange={e => handleFilterChange({ speaker: e.target.value || undefined })}
                  className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-primary-400">
                  <option value="">Oricine</option>
                  {speakers.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
              </div>
            )}
          </div>

          {hasActiveFilters && (
            <button onClick={clearFilters}
              className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-rose-600 transition-colors">
              <X className="h-3.5 w-3.5" />
              Resetează filtrele
            </button>
          )}
        </div>
      )}

      {error && (
        <div className="card p-4 text-sm text-rose-600 bg-rose-50 border-rose-200 mb-4">{error}</div>
      )}

      {response === null && !loading && (
        <EmptyState
          icon={Search}
          title="Caută în toate transcrierile"
        />
      )}

      {response !== null && (
        <div>
          {!response.semantic_available && (
            <div className="flex items-start gap-2 p-3 mb-4 text-xs rounded-lg bg-amber-50 border border-amber-200 text-amber-800">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              Căutarea după sens nu este disponibilă acum. Rezultatele de mai jos sunt doar potriviri exacte.
            </div>
          )}

          {nothingFound ? (
            <p className="text-sm text-slate-500 font-medium mb-4">Niciun rezultat găsit.</p>
          ) : (
            <div className="flex items-center gap-3 mb-4 flex-wrap">
              <p className="text-sm text-slate-500 font-medium">
                {response.total_hits} fragmente în {response.total_groups} ședințe
              </p>
              {response.total_hits > 0 && (
                <div className="flex gap-1.5">
                  <SourcePill source="both" count={response.both_count} />
                  <SourcePill source="fts" count={response.fts_count - response.both_count} />
                  <SourcePill source="semantic" count={response.semantic_count - response.both_count} />
                </div>
              )}
            </div>
          )}

          {page === 1 && response.recordings.length > 0 && (
            <section className="mb-5">
              <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">
                Ședințe găsite după titlu sau detalii
              </h2>
              <div className="space-y-2">
                {response.recordings.map(r => <RecordingMatchCard key={r.recording_id} match={r} />)}
              </div>
            </section>
          )}

          <div className="space-y-3 mb-4">
            {response.groups.map(g => <GroupCard key={g.recording_id} group={g} query={submitted} />)}
          </div>

          {response.pages > 1 && (
            <Pagination page={page} pages={response.pages} total={response.total_groups} onPageChange={changePage} />
          )}
        </div>
      )}
    </div>
  )
}

function sanitize(html: string): string {
  return DOMPurify.sanitize(html, { ALLOWED_TAGS: ['mark'], ALLOWED_ATTR: ['class'] })
}

function markHeadline(headline: string): string {
  return headline.replace(/<b>/g, MARK).replace(/<\/b>/g, '</mark>')
}

function RecordingMatchCard({ match }: { match: RecordingMatch }) {
  return (
    <Link to={`/recordings/${match.recording_id}`}
      className="flex items-start gap-3 card p-3 hover:border-primary-200 hover:shadow-md transition-all">
      <FileText className="h-4 w-4 text-primary-500 mt-0.5 shrink-0" />
      <div className="min-w-0">
        <p className="text-sm font-semibold text-slate-900">{match.title}</p>
        {match.headline && (
          <p className="text-xs text-slate-500 mt-0.5 line-clamp-2"
            dangerouslySetInnerHTML={{ __html: sanitize(markHeadline(match.headline)) }} />
        )}
        <p className="text-xs text-slate-400 mt-0.5">
          {new Date(match.meeting_date).toLocaleDateString('ro-RO')}
          {match.location && ` · ${match.location}`}
        </p>
      </div>
    </Link>
  )
}

function GroupCard({ group, query }: { group: SearchGroup; query: string }) {
  const more = group.total_hits - group.hits.length
  return (
    <section className="card p-4">
      <div className="flex items-start justify-between gap-3 mb-2">
        <Link to={`/recordings/${group.recording_id}`} className="text-sm font-semibold text-slate-900 hover:text-primary-700">
          {group.recording_title}
        </Link>
        <div className="flex items-center gap-1 text-xs text-slate-400 shrink-0">
          <Clock className="h-3 w-3" />
          {new Date(group.meeting_date).toLocaleDateString('ro-RO')}
        </div>
      </div>
      <div className="divide-y divide-slate-100">
        {group.hits.map(h => <HitRow key={h.segment_id} hit={h} query={query} />)}
      </div>
      {more > 0 && (
        <Link to={`/recordings/${group.recording_id}`} className="block mt-2 text-xs font-medium text-primary-600 hover:underline">
          încă {more} {more === 1 ? 'fragment' : 'fragmente'} în această ședință
        </Link>
      )}
    </section>
  )
}

function HitRow({ hit: h, query }: { hit: CombinedSearchResult; query: string }) {
  const html = sanitize(h.headline ? markHeadline(h.headline) : highlight(h.text, query))
  return (
    <Link to={`/recordings/${h.recording_id}?t=${h.start_time}`}
      className="block py-2 -mx-2 px-2 rounded-lg hover:bg-slate-50 transition-colors">
      <div className="flex items-center gap-2 mb-1 text-xs">
        <span className="font-medium text-primary-600">{formatTimestamp(h.start_time)}</span>
        {h.speaker_name && (
          <span className="inline-flex items-center gap-1 text-slate-500"><User className="h-3 w-3" />{h.speaker_name}</span>
        )}
        <span className="ml-auto"><SourceBadge source={h.source} /></span>
      </div>
      <p className="text-sm text-slate-600 leading-relaxed" dangerouslySetInnerHTML={{ __html: html }} />
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
  return text.replace(new RegExp(`(${escaped})`, 'gi'), `${MARK}$1</mark>`)
}

function formatTimestamp(sec: number): string {
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = String(Math.floor(sec % 60)).padStart(2, '0')
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`
}
