import { useRef, useState, useEffect, useCallback } from 'react'
import { Play, Pause, Volume2, VolumeX } from 'lucide-react'
import { cn } from '@/lib/cn'

interface AudioPlayerProps {
  src: string
  onTimeUpdate?: (currentTime: number) => void
  seekTo?: number | null
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  const h = Math.floor(m / 60)
  if (h > 0) return `${h}:${String(m % 60).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  return `${m}:${String(s).padStart(2, '0')}`
}

export default function AudioPlayer({ src, onTimeUpdate, seekTo }: AudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const [playing, setPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [muted, setMuted] = useState(false)
  const [error, setError] = useState(false)

  // Seek extern (din TranscriptViewer)
  useEffect(() => {
    if (seekTo !== null && seekTo !== undefined && audioRef.current) {
      audioRef.current.currentTime = seekTo
      audioRef.current.play()
      setPlaying(true)
    }
  }, [seekTo])

  const handleTimeUpdate = useCallback(() => {
    const t = audioRef.current?.currentTime ?? 0
    setCurrentTime(t)
    onTimeUpdate?.(t)
  }, [onTimeUpdate])

  const handleLoadedMetadata = () => {
    setDuration(audioRef.current?.duration ?? 0)
    setError(false)
  }

  const handleError = () => setError(true)

  const togglePlay = () => {
    if (!audioRef.current) return
    if (playing) {
      audioRef.current.pause()
    } else {
      audioRef.current.play()
    }
    setPlaying(!playing)
  }

  const handleEnded = () => setPlaying(false)

  const handleProgressClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!audioRef.current || !duration) return
    const rect = e.currentTarget.getBoundingClientRect()
    const ratio = (e.clientX - rect.left) / rect.width
    audioRef.current.currentTime = ratio * duration
  }

  const progress = duration ? (currentTime / duration) * 100 : 0

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-center text-sm text-red-600">
        Nu s-a putut încărca fișierul audio.
      </div>
    )
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <audio
        ref={audioRef}
        src={src}
        onTimeUpdate={handleTimeUpdate}
        onLoadedMetadata={handleLoadedMetadata}
        onEnded={handleEnded}
        onError={handleError}
        preload="metadata"
      />

      <div className="flex items-center gap-4">
        {/* Play/Pause */}
        <button
          onClick={togglePlay}
          className="h-10 w-10 rounded-full bg-blue-600 hover:bg-blue-700 flex items-center justify-center text-white transition-colors shrink-0"
        >
          {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4 ml-0.5" />}
        </button>

        {/* Progress bar */}
        <div className="flex-1 flex items-center gap-3">
          <span className="text-xs text-gray-500 w-10 shrink-0">{formatTime(currentTime)}</span>
          <div
            className="flex-1 h-2 bg-gray-200 rounded-full cursor-pointer relative"
            onClick={handleProgressClick}
          >
            <div
              className="h-2 bg-blue-600 rounded-full transition-all"
              style={{ width: `${progress}%` }}
            />
          </div>
          <span className="text-xs text-gray-500 w-10 shrink-0 text-right">{formatTime(duration)}</span>
        </div>

        {/* Mute */}
        <button
          onClick={() => {
            if (audioRef.current) audioRef.current.muted = !muted
            setMuted(!muted)
          }}
          className={cn('p-1.5 rounded-lg transition-colors', muted ? 'text-red-500' : 'text-gray-400 hover:text-gray-600')}
        >
          {muted ? <VolumeX className="h-4 w-4" /> : <Volume2 className="h-4 w-4" />}
        </button>
      </div>
    </div>
  )
}
