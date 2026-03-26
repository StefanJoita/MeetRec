import { useEffect, useRef, useState, useCallback, useMemo } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { Search, X, ChevronUp, ChevronDown } from 'lucide-react'
import type { TranscriptSegment as Segment } from '@/api/types'
import { cn } from '@/lib/cn'
import { formatTime } from '@/lib/formatTime'

interface TranscriptViewerProps {
  segments: Segment[]
  getCurrentTime: () => number
  onSegmentClick: (startTime: number) => void
}

function getActiveIndex(segments: Segment[], currentTime: number): number {
  for (let i = segments.length - 1; i >= 0; i--) {
    if (currentTime >= segments[i].start_time) return i
  }
  return -1
}

/** Marchează textul cu highlight pentru query-ul curent */
function HighlightedText({ text, query }: { text: string; query: string }) {
  if (!query) return <>{text}</>
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const parts = text.split(new RegExp(`(${escaped})`, 'gi'))
  return (
    <>
      {parts.map((part, i) =>
        part.toLowerCase() === query.toLowerCase() ? (
          <mark key={i} className="bg-yellow-200 text-yellow-900 rounded-sm px-0.5">
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </>
  )
}

export default function TranscriptViewer({ segments, getCurrentTime, onSegmentClick }: TranscriptViewerProps) {
  const [activeIndex, setActiveIndex] = useState(-1)
  const parentRef   = useRef<HTMLDivElement>(null)
  const searchRef   = useRef<HTMLInputElement>(null)

  // RAF intern — actualizează activeIndex la ~10fps fără a re-renda pagina-părinte
  const rafRef        = useRef<number | null>(null)
  const lastTickRef   = useRef(0)
  const getTimeRef    = useRef(getCurrentTime)
  getTimeRef.current  = getCurrentTime
  const segmentsRef   = useRef(segments)
  segmentsRef.current = segments

  useEffect(() => {
    const tick = (now: number) => {
      if (now - lastTickRef.current >= 50) {
        lastTickRef.current = now
        const t = getTimeRef.current()
        setActiveIndex(prev => {
          const next = getActiveIndex(segmentsRef.current, t)
          return next !== prev ? next : prev
        })
      }
      rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current) }
  }, [])

  const [searchOpen,  setSearchOpen]  = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [matchCursor, setMatchCursor] = useState(0)

  // Indicii segmentelor care conțin query-ul
  const matchIndices = useMemo<number[]>(() => {
    if (!searchQuery.trim()) return []
    const q = searchQuery.toLowerCase()
    return segments.reduce<number[]>((acc, seg, i) => {
      if (seg.text.toLowerCase().includes(q)) acc.push(i)
      return acc
    }, [])
  }, [segments, searchQuery])

  const virtualizer = useVirtualizer({
    count: segments.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 56,
    overscan: 5,
  })

  // Ctrl+F deschide bara de căutare
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
        e.preventDefault()
        setSearchOpen(true)
        setTimeout(() => searchRef.current?.focus(), 50)
      }
      if (e.key === 'Escape' && searchOpen) closeSearch()
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [searchOpen])

  // Scroll la primul match când se schimbă query-ul
  useEffect(() => {
    if (matchIndices.length > 0) {
      setMatchCursor(0)
      virtualizer.scrollToIndex(matchIndices[0], { align: 'center' })
    }
  }, [matchIndices]) // eslint-disable-line react-hooks/exhaustive-deps

  // Scroll la matchCursor curent
  useEffect(() => {
    if (matchIndices.length > 0) {
      virtualizer.scrollToIndex(matchIndices[matchCursor], { align: 'center' })
    }
  }, [matchCursor]) // eslint-disable-line react-hooks/exhaustive-deps

  // Scroll automat la segmentul activ (când nu căutăm)
  useEffect(() => {
    if (!searchQuery && activeIndex >= 0) {
      virtualizer.scrollToIndex(activeIndex, { behavior: 'smooth', align: 'auto' })
    }
  }, [activeIndex]) // eslint-disable-line react-hooks/exhaustive-deps

  const closeSearch = useCallback(() => {
    setSearchOpen(false)
    setSearchQuery('')
    setMatchCursor(0)
  }, [])

  function stepMatch(dir: 1 | -1) {
    if (!matchIndices.length) return
    setMatchCursor(c => (c + dir + matchIndices.length) % matchIndices.length)
  }

  if (!segments.length) {
    return (
      <div className="text-center py-12 text-gray-400 text-sm">
        Nu există segmente de transcriere.
      </div>
    )
  }

  const items = virtualizer.getVirtualItems()
  const currentMatchSegIdx = matchIndices[matchCursor] ?? -1

  return (
    <div>
      {/* Hint + search trigger */}
      <div className="flex items-center justify-between mb-3 px-3">
        <p className="text-xs text-gray-400">
          Apasă pe orice segment pentru a sări la momentul respectiv în înregistrare.
        </p>
        <button
          onClick={() => { setSearchOpen(true); setTimeout(() => searchRef.current?.focus(), 50) }}
          className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-slate-600 transition-colors"
          title="Caută în transcript (Ctrl+F)"
        >
          <Search className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">Ctrl+F</span>
        </button>
      </div>

      {/* Search bar */}
      {searchOpen && (
        <div className="flex items-center gap-2 mb-3 px-3 py-2 bg-slate-50 border border-slate-200 rounded-xl animate-slide-up">
          <Search className="h-4 w-4 text-slate-400 shrink-0" />
          <input
            ref={searchRef}
            type="text"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') { e.preventDefault(); stepMatch(e.shiftKey ? -1 : 1) }
              if (e.key === 'Escape') closeSearch()
            }}
            placeholder="Caută în transcript…"
            className="flex-1 bg-transparent text-sm outline-none text-slate-700 placeholder:text-slate-400"
          />
          {searchQuery && (
            <span className="text-xs text-slate-400 shrink-0 tabular-nums">
              {matchIndices.length
                ? `${matchCursor + 1}/${matchIndices.length}`
                : 'Nicio potrivire'}
            </span>
          )}
          <div className="flex items-center gap-1">
            <button
              onClick={() => stepMatch(-1)}
              disabled={matchIndices.length === 0}
              className="p-1 rounded hover:bg-slate-200 disabled:opacity-30 transition-colors"
              aria-label="Rezultat anterior"
            >
              <ChevronUp className="h-3.5 w-3.5" />
            </button>
            <button
              onClick={() => stepMatch(1)}
              disabled={matchIndices.length === 0}
              className="p-1 rounded hover:bg-slate-200 disabled:opacity-30 transition-colors"
              aria-label="Rezultat următor"
            >
              <ChevronDown className="h-3.5 w-3.5" />
            </button>
            <button
              onClick={closeSearch}
              className="p-1 rounded hover:bg-slate-200 transition-colors ml-1"
              aria-label="Închide căutarea"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}

      <div
        ref={parentRef}
        className="overflow-auto"
        style={{ height: '480px' }}
        role="list"
        aria-label="Segmente transcriere"
      >
        <div style={{ height: `${virtualizer.getTotalSize()}px`, position: 'relative' }}>
          {items.map((virtualItem) => {
            const seg       = segments[virtualItem.index]
            const isActive  = virtualItem.index === activeIndex && !searchQuery
            const isMatch   = searchQuery
              ? seg.text.toLowerCase().includes(searchQuery.toLowerCase())
              : false
            const isCurrent = virtualItem.index === currentMatchSegIdx

            return (
              <div
                key={virtualItem.key}
                data-index={virtualItem.index}
                ref={virtualizer.measureElement}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  transform: `translateY(${virtualItem.start}px)`,
                }}
                role="listitem"
              >
                <button
                  type="button"
                  aria-label={`Segment la ${formatTime(seg.start_time)}: ${seg.text}`}
                  aria-current={isActive ? 'true' : undefined}
                  onClick={() => onSegmentClick(seg.start_time)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      onSegmentClick(seg.start_time)
                    }
                  }}
                  className={cn(
                    'w-full text-left flex gap-3 px-3 py-2.5 rounded-lg cursor-pointer transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500',
                    isCurrent
                      ? 'bg-yellow-50 border-l-4 border-yellow-400'
                      : isMatch
                        ? 'bg-yellow-50/40 border-l-4 border-yellow-200'
                        : isActive
                          ? 'bg-blue-50 border-l-4 border-blue-500'
                          : 'hover:bg-gray-50 border-l-4 border-transparent'
                  )}
                >
                  <span className="text-xs font-mono text-gray-400 pt-0.5 shrink-0 w-12" aria-hidden="true">
                    {formatTime(seg.start_time)}
                  </span>
                  <p className={cn('text-sm leading-relaxed', isActive ? 'text-gray-900 font-medium' : 'text-gray-700')}>
                    <HighlightedText text={seg.text} query={searchQuery} />
                  </p>
                  {seg.confidence !== undefined && seg.confidence !== null && (
                    <span
                      className={cn(
                        'text-xs shrink-0 pt-0.5',
                        seg.confidence < 0.7 ? 'text-orange-400' : 'text-gray-300'
                      )}
                      aria-label={`Acuratețe ${Math.round(seg.confidence * 100)}%`}
                    >
                      {Math.round(seg.confidence * 100)}%
                    </span>
                  )}
                </button>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
