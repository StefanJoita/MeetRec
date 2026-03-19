import { useEffect, useRef } from 'react'
import type { TranscriptSegment as Segment } from '@/api/types'
import { cn } from '@/lib/cn'

interface TranscriptViewerProps {
  segments: Segment[]
  currentTime: number
  onSegmentClick: (startTime: number) => void
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  const h = Math.floor(m / 60)
  if (h > 0) return `${h}:${String(m % 60).padStart(2, '0')}:${String(s).padStart(2, '00')}`
  return `${m}:${String(s).padStart(2, '0')}`
}

function getActiveIndex(segments: Segment[], currentTime: number): number {
  for (let i = segments.length - 1; i >= 0; i--) {
    if (currentTime >= segments[i].start_time) return i
  }
  return -1
}

export default function TranscriptViewer({ segments, currentTime, onSegmentClick }: TranscriptViewerProps) {
  const activeIndex = getActiveIndex(segments, currentTime)
  const activeRef = useRef<HTMLDivElement>(null)

  // Auto-scroll la segmentul curent
  useEffect(() => {
    activeRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [activeIndex])

  if (!segments.length) {
    return (
      <div className="text-center py-12 text-gray-400 text-sm">
        Nu există segmente de transcriere.
      </div>
    )
  }

  return (
    <div className="space-y-1">
      {segments.map((seg, i) => {
        const isActive = i === activeIndex
        return (
          <div
            key={seg.id}
            ref={isActive ? activeRef : null}
            onClick={() => onSegmentClick(seg.start_time)}
            className={cn(
              'flex gap-3 px-3 py-2.5 rounded-lg cursor-pointer transition-colors',
              isActive
                ? 'bg-blue-50 border-l-4 border-blue-500'
                : 'hover:bg-gray-50 border-l-4 border-transparent'
            )}
          >
            <span className="text-xs font-mono text-gray-400 pt-0.5 shrink-0 w-12">
              {formatTime(seg.start_time)}
            </span>
            <p className={cn('text-sm leading-relaxed', isActive ? 'text-gray-900 font-medium' : 'text-gray-700')}>
              {seg.text}
            </p>
            {seg.confidence !== undefined && seg.confidence !== null && (
              <span className="text-xs text-gray-300 shrink-0 pt-0.5">
                {Math.round(seg.confidence * 100)}%
              </span>
            )}
          </div>
        )
      })}
    </div>
  )
}
