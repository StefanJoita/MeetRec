import { useRef, useState, useEffect, useCallback } from 'react'
import { Play, Pause, Volume2, VolumeX, SkipBack, SkipForward } from 'lucide-react'
import { cn } from '@/lib/cn'
import { formatTime } from '@/lib/formatTime'

interface AudioPlayerProps {
  src: string
  onTimeUpdate?: (currentTime: number) => void
  seekTo?: number | null
}

const SPEEDS = [0.75, 1, 1.25, 1.5, 2]
const SKIP_SEC = 15

/**
 * Construiește URL-ul audio cu token JWT ca query param.
 * <audio> nu poate trimite header-uri custom, deci autentificarea
 * se face prin ?token= — backend-ul acceptă ambele metode.
 */
function buildAudioSrc(src: string): string {
  const token = localStorage.getItem('access_token')
  if (!token || src.includes('?token=')) return src
  return `${src}?token=${encodeURIComponent(token)}`
}

export default function AudioPlayer({ src, onTimeUpdate, seekTo }: AudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const [playing, setPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [muted, setMuted] = useState(false)
  const [speed, setSpeed] = useState(1)
  const [error, setError] = useState(false)

  // Construim URL-ul cu token la fiecare schimbare de src
  const audioSrc = src ? buildAudioSrc(src) : undefined

  // Seek extern (din TranscriptViewer)
  useEffect(() => {
    if (seekTo !== null && seekTo !== undefined && audioRef.current) {
      audioRef.current.currentTime = seekTo
      audioRef.current.play()
      setPlaying(true)
    }
  }, [seekTo])

  // Reset error la schimbarea sursei
  useEffect(() => {
    setError(false)
    setPlaying(false)
    setCurrentTime(0)
    setDuration(0)
  }, [src])

  const handleTimeUpdate = useCallback(() => {
    const t = audioRef.current?.currentTime ?? 0
    setCurrentTime(t)
    onTimeUpdate?.(t)
  }, [onTimeUpdate])

  const handleLoadedMetadata = () => {
    setDuration(audioRef.current?.duration ?? 0)
    setError(false)
  }

  const togglePlay = () => {
    if (!audioRef.current) return
    if (playing) {
      audioRef.current.pause()
    } else {
      audioRef.current.play()
    }
    setPlaying(!playing)
  }

  const skip = (sec: number) => {
    if (!audioRef.current) return
    audioRef.current.currentTime = Math.max(0, Math.min(duration, currentTime + sec))
  }

  const handleProgressClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!audioRef.current || !duration) return
    const rect = e.currentTarget.getBoundingClientRect()
    audioRef.current.currentTime = ((e.clientX - rect.left) / rect.width) * duration
  }

  const handleProgressKeyDown = (e: React.KeyboardEvent) => {
    if (!audioRef.current || !duration) return
    if (e.key === 'ArrowRight') skip(5)
    else if (e.key === 'ArrowLeft') skip(-5)
  }

  const cycleSpeed = () => {
    const next = SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length]
    setSpeed(next)
    if (audioRef.current) audioRef.current.playbackRate = next
  }

  const toggleMute = () => {
    if (audioRef.current) audioRef.current.muted = !muted
    setMuted(!muted)
  }

  const progress = duration ? (currentTime / duration) * 100 : 0

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-center text-sm text-red-600">
        Nu s-a putut încărca fișierul audio. Sesiunea poate fi expirată — reîncarcă pagina.
      </div>
    )
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      {/* Audio nativ — browser-ul face range requests automat pentru streaming */}
      <audio
        ref={audioRef}
        src={audioSrc}
        onTimeUpdate={handleTimeUpdate}
        onLoadedMetadata={handleLoadedMetadata}
        onEnded={() => setPlaying(false)}
        onError={() => setError(true)}
        preload="metadata"
      />

      <div className="flex items-center gap-3">
        {/* Skip înapoi */}
        <button
          onClick={() => skip(-SKIP_SEC)}
          aria-label={`Înapoi ${SKIP_SEC} secunde`}
          className="btn-ghost shrink-0"
        >
          <SkipBack className="h-4 w-4" />
        </button>

        {/* Play/Pause */}
        <button
          onClick={togglePlay}
          aria-label={playing ? 'Pauză' : 'Redă'}
          className="h-10 w-10 rounded-full bg-blue-600 hover:bg-blue-700 flex items-center justify-center text-white transition-colors shrink-0"
        >
          {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4 ml-0.5" />}
        </button>

        {/* Skip înainte */}
        <button
          onClick={() => skip(SKIP_SEC)}
          aria-label={`Înainte ${SKIP_SEC} secunde`}
          className="btn-ghost shrink-0"
        >
          <SkipForward className="h-4 w-4" />
        </button>

        {/* Progress bar */}
        <div className="flex-1 flex items-center gap-2 min-w-0">
          <span className="text-xs text-gray-500 w-10 shrink-0 tabular-nums" aria-hidden="true">
            {formatTime(currentTime)}
          </span>
          <div
            role="slider"
            aria-label="Progres redare"
            aria-valuenow={Math.round(currentTime)}
            aria-valuemin={0}
            aria-valuemax={Math.round(duration)}
            aria-valuetext={`${formatTime(currentTime)} din ${formatTime(duration)}`}
            tabIndex={0}
            className="flex-1 h-2 bg-gray-200 rounded-full cursor-pointer relative focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            onClick={handleProgressClick}
            onKeyDown={handleProgressKeyDown}
          >
            <div
              className="h-2 bg-blue-600 rounded-full transition-all pointer-events-none"
              style={{ width: `${progress}%` }}
              aria-hidden="true"
            />
          </div>
          <span className="text-xs text-gray-500 w-10 shrink-0 text-right tabular-nums" aria-hidden="true">
            {formatTime(duration)}
          </span>
        </div>

        {/* Viteză */}
        <button
          onClick={cycleSpeed}
          aria-label={`Viteză redare: ${speed}x. Apasă pentru a schimba.`}
          className="text-xs font-medium text-gray-500 hover:text-blue-600 w-9 text-center transition-colors shrink-0"
        >
          {speed}x
        </button>

        {/* Mute */}
        <button
          onClick={toggleMute}
          aria-label={muted ? 'Activează sunet' : 'Dezactivează sunet'}
          className={cn('p-1.5 rounded-lg transition-colors shrink-0', muted ? 'text-red-500' : 'text-gray-400 hover:text-gray-600')}
        >
          {muted ? <VolumeX className="h-4 w-4" /> : <Volume2 className="h-4 w-4" />}
        </button>
      </div>
    </div>
  )
}
