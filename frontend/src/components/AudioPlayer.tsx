import { useRef, useState, useEffect, useCallback, forwardRef, useImperativeHandle } from 'react'
import { Play, Pause, Volume2, VolumeX, SkipBack, SkipForward } from 'lucide-react'
import { cn } from '@/lib/cn'
import { formatTime } from '@/lib/formatTime'
import { getAudioToken, buildAudioUrl } from '@/api/recordings'

interface AudioPlayerProps {
  recordingId: string
  onTimeUpdate?: (currentTime: number) => void
}

export interface AudioPlayerHandle {
  seek: (time: number) => void
}

const SPEEDS   = [0.75, 1, 1.25, 1.5, 2]
const SKIP_SEC = 15

const AudioPlayer = forwardRef<AudioPlayerHandle, AudioPlayerProps>(function AudioPlayer(
  { recordingId, onTimeUpdate },
  ref,
) {
  const audioRef    = useRef<HTMLAudioElement>(null)
  const rafRef      = useRef<number | null>(null)
  const onTimeUpdateRef = useRef(onTimeUpdate)
  onTimeUpdateRef.current = onTimeUpdate

  const [playing, setPlaying]     = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration]   = useState(0)
  const [muted, setMuted]         = useState(false)
  const [speed, setSpeed]         = useState(1)
  const [error, setError]         = useState(false)
  const [audioSrc, setAudioSrc]   = useState<string | undefined>(undefined)

  useEffect(() => {
    if (!recordingId) return
    setAudioSrc(undefined)
    setError(false)
    getAudioToken(recordingId)
      .then(token => setAudioSrc(buildAudioUrl(recordingId, token)))
      .catch(() => setError(true))
  }, [recordingId])

  useImperativeHandle(ref, () => ({
    seek(time: number) {
      const audio = audioRef.current
      if (!audio) return

      const doSeek = () => {
        audio.currentTime = time
        audio.play().catch(() => {})
        setPlaying(true)
      }

      if (audio.readyState >= HTMLMediaElement.HAVE_METADATA) {
        doSeek()
      } else {
        audio.addEventListener('loadedmetadata', doSeek, { once: true })
      }
    },
  }))

  useEffect(() => {
    setError(false)
    setPlaying(false)
    setCurrentTime(0)
    setDuration(0)
  }, [recordingId])

  // RAF loop — actualizare la 60fps cât timp audio-ul e în redare
  useEffect(() => {
    if (!playing) {
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
      return
    }
    const tick = () => {
      const t = audioRef.current?.currentTime ?? 0
      setCurrentTime(t)
      onTimeUpdateRef.current?.(t)
      rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current) }
  }, [playing])

  const handleTimeUpdate = useCallback(() => {
    // Fallback pentru when RAF nu rulează (pauză, seek manual)
    const t = audioRef.current?.currentTime ?? 0
    setCurrentTime(t)
    onTimeUpdateRef.current?.(t)
  }, [])

  const handleLoadedMetadata = () => {
    setDuration(audioRef.current?.duration ?? 0)
    setError(false)
  }

  const togglePlay = () => {
    if (!audioRef.current) return
    if (playing) { audioRef.current.pause() } else { audioRef.current.play() }
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
      <div className="bg-rose-50 border border-rose-200 rounded-xl p-4 text-center text-sm text-rose-600">
        Nu s-a putut încărca fișierul audio. Sesiunea poate fi expirată — reîncarcă pagina.
      </div>
    )
  }

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-4">
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
          className={cn(
            'h-10 w-10 rounded-full flex items-center justify-center shrink-0 transition-all duration-150',
            'bg-primary-600 hover:bg-primary-700 text-white shadow-sm hover:shadow-md'
          )}
        >
          {playing
            ? <Pause className="h-4 w-4" />
            : <Play  className="h-4 w-4 ml-0.5" />
          }
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
        <div className="flex-1 flex items-center gap-2.5 min-w-0">
          <span className="text-xs text-slate-500 w-10 shrink-0 tabular-nums" aria-hidden="true">
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
            className="flex-1 group relative h-2 bg-slate-200 rounded-full cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500"
            onClick={handleProgressClick}
            onKeyDown={handleProgressKeyDown}
          >
            {/* Fill */}
            <div
              className="h-2 bg-primary-600 rounded-full transition-all pointer-events-none"
              style={{ width: `${progress}%` }}
              aria-hidden="true"
            />
            {/* Thumb — visible on hover/focus */}
            <div
              className="absolute top-1/2 -translate-y-1/2 h-4 w-4 bg-white rounded-full border-2 border-primary-600 shadow-sm pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity"
              style={{ left: `calc(${progress}% - 8px)` }}
              aria-hidden="true"
            />
          </div>

          <span className="text-xs text-slate-500 w-10 shrink-0 text-right tabular-nums" aria-hidden="true">
            {formatTime(duration)}
          </span>
        </div>

        {/* Viteză */}
        <button
          onClick={cycleSpeed}
          aria-label={`Viteză redare: ${speed}x. Apasă pentru a schimba.`}
          className={cn(
            'text-xs font-semibold w-10 h-8 rounded-lg text-center transition-all duration-150 shrink-0',
            speed !== 1
              ? 'bg-primary-50 text-primary-600'
              : 'text-slate-400 hover:text-slate-700 hover:bg-slate-100'
          )}
        >
          {speed}x
        </button>

        {/* Mute */}
        <button
          onClick={toggleMute}
          aria-label={muted ? 'Activează sunet' : 'Dezactivează sunet'}
          className={cn(
            'p-1.5 rounded-lg transition-colors shrink-0',
            muted ? 'text-rose-500 bg-rose-50' : 'text-slate-400 hover:text-slate-600 hover:bg-slate-100'
          )}
        >
          {muted ? <VolumeX className="h-4 w-4" /> : <Volume2 className="h-4 w-4" />}
        </button>
      </div>
    </div>
  )
})

export default AudioPlayer
