import { useEffect, useRef } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import type { TranscriptSegment as Segment } from '@/api/types'
import { cn } from '@/lib/cn'
import { formatTime } from '@/lib/formatTime'

interface TranscriptViewerProps {
  segments: Segment[]
  currentTime: number
  onSegmentClick: (startTime: number) => void
}

function getActiveIndex(segments: Segment[], currentTime: number): number {
  for (let i = segments.length - 1; i >= 0; i--) {
    if (currentTime >= segments[i].start_time) return i
  }
  return -1
}

export default function TranscriptViewer({ segments, currentTime, onSegmentClick }: TranscriptViewerProps) {
  const activeIndex = getActiveIndex(segments, currentTime)
  const parentRef = useRef<HTMLDivElement>(null)

  const virtualizer = useVirtualizer({
    count: segments.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 56,
    overscan: 5,
  })

  // Scroll automat la segmentul activ
  useEffect(() => {
    if (activeIndex >= 0) {
      virtualizer.scrollToIndex(activeIndex, { behavior: 'smooth', align: 'auto' })
    }
  }, [activeIndex]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!segments.length) {
    return (
      <div className="text-center py-12 text-gray-400 text-sm">
        Nu există segmente de transcriere.
      </div>
    )
  }

  const items = virtualizer.getVirtualItems()

  return (
    <div>
      <p className="text-xs text-gray-400 mb-3 px-3">
        Apasă pe orice segment pentru a sări la momentul respectiv în înregistrare.
      </p>
      <div
        ref={parentRef}
        className="overflow-auto"
        style={{ height: '480px' }}
        role="list"
        aria-label="Segmente transcriere"
      >
        <div
          style={{ height: `${virtualizer.getTotalSize()}px`, position: 'relative' }}
        >
          {items.map((virtualItem) => {
            const seg = segments[virtualItem.index]
            const isActive = virtualItem.index === activeIndex
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
                    isActive
                      ? 'bg-blue-50 border-l-4 border-blue-500'
                      : 'hover:bg-gray-50 border-l-4 border-transparent'
                  )}
                >
                  <span className="text-xs font-mono text-gray-400 pt-0.5 shrink-0 w-12" aria-hidden="true">
                    {formatTime(seg.start_time)}
                  </span>
                  <p className={cn('text-sm leading-relaxed', isActive ? 'text-gray-900 font-medium' : 'text-gray-700')}>
                    {seg.text}
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
