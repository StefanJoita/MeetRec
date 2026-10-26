// Înregistrarea ședințelor din browser.
//
// Fluxul: microfon → AudioWorklet (lib/recording/recorder-worklet.js) → 16 kHz mono →
// segmente WAV de 5 minute → /inbox/upload, cu același session_id. La oprire,
// /session/{id}/complete pornește transcrierea. Serverul tratează sesiunea exact
// ca pe cele multi-segment: Ingest validează fiecare segment, STT Worker le lipește.
//
// Starea stă într-un context deasupra paginilor, ca înregistrarea să continue
// când utilizatorul navighează prin aplicație în timpul ședinței.

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import {
  completeRecordingSession, createRecordingSession, refreshAccessToken, uploadSessionSegment,
  type SessionMetadata,
} from '@/api/recordingSession'
import { Downsampler, encodeWav, SegmentBuffer, signalLevel, TARGET_SAMPLE_RATE, toInt16 } from '@/lib/recording/audio'
import { errorMessage, SegmentUploader, type UploaderStatus } from '@/lib/recording/segmentUploader'
import workletUrl from '@/lib/recording/recorder-worklet.js?url&no-inline'

export type RecorderPhase =
  | 'idle'        // microfonul nu e deschis
  | 'requesting'  // se cere accesul la microfon
  | 'ready'       // microfon deschis, indicator de nivel, se poate porni
  | 'starting'    // se creează sesiunea pe server
  | 'recording'
  | 'finishing'   // se trimit ultimele segmente și se pornește transcrierea
  | 'done'
  | 'error'

export interface AudioInput {
  deviceId: string
  label: string
}

interface RecorderState {
  phase: RecorderPhase
  devices: AudioInput[]
  deviceId: string
  level: number
  elapsedSeconds: number
  segments: number
  upload: UploaderStatus
  error: string
  warning: string
  title: string             // titlul ședinței în curs (formularul se pierde la navigare)
  recordingId: string | null
}

interface RecorderContextType extends RecorderState {
  supported: boolean
  enableMicrophone: (deviceId?: string) => Promise<void>
  start: (meta: SessionMetadata) => Promise<void>
  stop: () => Promise<void>
  reset: () => void
  /** Înregistrare în curs sau segmente încă netrimise: închiderea paginii pierde audio. */
  busy: boolean
}

const TOKEN_REFRESH_MS = 30 * 60_000
const UI_TICK_MS = 200
const COMPLETE_ATTEMPTS = 6
const COMPLETE_RETRY_MS = 5_000

const EMPTY_UPLOAD: UploaderStatus = { uploaded: 0, pending: 0, failed: 0, retrying: false, lastError: '' }

const INITIAL: RecorderState = {
  phase: 'idle', devices: [], deviceId: '', level: 0, elapsedSeconds: 0, segments: 0,
  upload: EMPTY_UPLOAD, error: '', warning: '', title: '', recordingId: null,
}

const RecorderContext = createContext<RecorderContextType | null>(null)

/** Microfonul e disponibil doar în context securizat (HTTPS sau localhost). */
export function isRecordingSupported(): boolean {
  return typeof window !== 'undefined' && window.isSecureContext && !!navigator.mediaDevices?.getUserMedia
    && typeof AudioWorkletNode !== 'undefined'
}

function microphoneError(e: unknown): string {
  const name = (e as { name?: string })?.name
  if (name === 'NotAllowedError' || name === 'SecurityError')
    return 'Accesul la microfon a fost refuzat. Permiteți-l din setările browserului (pictograma de lângă adresă) și încercați din nou.'
  if (name === 'NotFoundError' || name === 'OverconstrainedError')
    return 'Nu am găsit niciun microfon. Conectați unul și încercați din nou.'
  if (name === 'NotReadableError')
    return 'Microfonul e folosit de altă aplicație sau nu răspunde.'
  return 'Nu am putut porni microfonul.'
}

const sleep = (ms: number) => new Promise(r => setTimeout(r, ms))

export function RecorderProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<RecorderState>(INITIAL)
  const patch = useCallback((p: Partial<RecorderState>) => setState(s => ({ ...s, ...p })), [])

  const streamRef = useRef<MediaStream | null>(null)
  const ctxRef = useRef<AudioContext | null>(null)
  const downsamplerRef = useRef<Downsampler | null>(null)
  const bufferRef = useRef<SegmentBuffer | null>(null)
  const uploaderRef = useRef<SegmentUploader | null>(null)
  const sessionRef = useRef<string | null>(null)
  const recordingRef = useRef(false)
  const segmentIndexRef = useRef(0)
  const samplesRef = useRef(0)
  const levelRef = useRef(0)
  const wakeLockRef = useRef<WakeLockSentinel | null>(null)
  const refreshTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const stopRef = useRef<() => Promise<void>>(async () => {})

  const enqueueSegment = useCallback((samples: Int16Array) => {
    uploaderRef.current?.enqueue(segmentIndexRef.current++, encodeWav(samples))
    patch({ segments: segmentIndexRef.current })
  }, [patch])

  const onSamples = useCallback((block: Float32Array) => {
    levelRef.current = signalLevel(block)
    if (!recordingRef.current || !downsamplerRef.current || !bufferRef.current) return
    const pcm = toInt16(downsamplerRef.current.process(block))
    samplesRef.current += pcm.length
    for (const segment of bufferRef.current.push(pcm)) enqueueSegment(segment)
  }, [enqueueSegment])

  const releaseMicrophone = useCallback(() => {
    streamRef.current?.getTracks().forEach(t => { t.onended = null; t.stop() })
    streamRef.current = null
    void ctxRef.current?.close().catch(() => {})
    ctxRef.current = null
    levelRef.current = 0
  }, [])

  const listDevices = useCallback(async () => {
    const all = await navigator.mediaDevices.enumerateDevices()
    return all
      .filter(d => d.kind === 'audioinput')
      .map((d, i) => ({ deviceId: d.deviceId, label: d.label || `Microfon ${i + 1}` }))
  }, [])

  const enableMicrophone = useCallback(async (deviceId?: string) => {
    if (recordingRef.current) return
    releaseMicrophone()
    patch({ phase: 'requesting', error: '', warning: '' })
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          deviceId: deviceId ? { exact: deviceId } : undefined,
          // Prelucrările pentru apeluri video taie din vorbirea îndepărtată
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: true,
        },
      })
      const ctx = new AudioContext()
      await ctx.audioWorklet.addModule(workletUrl)
      const source = ctx.createMediaStreamSource(stream)
      const node = new AudioWorkletNode(ctx, 'meetrec-recorder')
      const mute = ctx.createGain()
      mute.gain.value = 0              // nodul trebuie legat la ieșire ca să ruleze, fără să se audă
      source.connect(node)
      node.connect(mute)
      mute.connect(ctx.destination)
      node.port.onmessage = (e: MessageEvent<Float32Array>) => onSamples(e.data)
      await ctx.resume()

      const track = stream.getAudioTracks()[0]
      track.onended = () => {
        if (recordingRef.current) {
          patch({ warning: 'Microfonul s-a deconectat. Am oprit înregistrarea și trimit ce s-a înregistrat până acum.' })
          void stopRef.current()
        } else {
          releaseMicrophone()
          patch({ phase: 'error', error: 'Microfonul s-a deconectat.' })
        }
      }

      streamRef.current = stream
      ctxRef.current = ctx
      downsamplerRef.current = new Downsampler(ctx.sampleRate, TARGET_SAMPLE_RATE)
      const devices = await listDevices()
      patch({ phase: 'ready', devices, deviceId: track.getSettings().deviceId ?? deviceId ?? '' })
    } catch (e) {
      releaseMicrophone()
      patch({ phase: 'error', error: microphoneError(e) })
    }
  }, [listDevices, onSamples, patch, releaseMicrophone])

  const acquireWakeLock = useCallback(async () => {
    try {
      wakeLockRef.current = await navigator.wakeLock?.request('screen') ?? null
    } catch {
      // Opțional: fără wake lock, calculatorul nu trebuie lăsat să intre în repaus
    }
  }, [])

  const start = useCallback(async (meta: SessionMetadata) => {
    if (!ctxRef.current || recordingRef.current) return
    patch({ phase: 'starting', error: '', warning: '', recordingId: null })
    let sessionId: string
    try {
      await refreshAccessToken()
      sessionId = await createRecordingSession(meta)
    } catch (e) {
      patch({ phase: 'ready', error: errorMessage(e, 'Nu am putut porni înregistrarea pe server. Încercați din nou.') })
      return
    }

    sessionRef.current = sessionId
    segmentIndexRef.current = 0
    samplesRef.current = 0
    bufferRef.current = new SegmentBuffer()
    downsamplerRef.current = new Downsampler(ctxRef.current.sampleRate, TARGET_SAMPLE_RATE)
    uploaderRef.current = new SegmentUploader({
      upload: (index, blob) => uploadSessionSegment(sessionId, index, blob),
      onChange: upload => patch({ upload }),
    })
    recordingRef.current = true
    patch({ phase: 'recording', segments: 0, elapsedSeconds: 0, upload: EMPTY_UPLOAD, title: meta.title })

    // Tokenul expiră după JWT_EXPIRE_MINUTES; o ședință lungă nu trebuie să rămână fără el
    refreshTimerRef.current = setInterval(() => { void refreshAccessToken().catch(() => {}) }, TOKEN_REFRESH_MS)
    void acquireWakeLock()
  }, [acquireWakeLock, patch])

  const stop = useCallback(async () => {
    if (!recordingRef.current) return
    recordingRef.current = false
    const sessionId = sessionRef.current!
    const uploader = uploaderRef.current!
    patch({ phase: 'finishing', elapsedSeconds: samplesRef.current / TARGET_SAMPLE_RATE })

    const last = bufferRef.current?.flush(segmentIndexRef.current === 0)
    if (last) enqueueSegment(last)
    const totalSegments = segmentIndexRef.current
    releaseMicrophone()
    void wakeLockRef.current?.release().catch(() => {})
    wakeLockRef.current = null

    await uploader.drain()
    if (refreshTimerRef.current) clearInterval(refreshTimerRef.current)
    refreshTimerRef.current = null

    for (let attempt = 1; ; attempt++) {
      try {
        const recordingId = await completeRecordingSession(sessionId, totalSegments)
        patch({ phase: 'done', recordingId })
        return
      } catch (e) {
        const status = (e as { response?: { status?: number } })?.response?.status
        const detail = errorMessage(e, '')
        // 409 fără „Reîncearcă”: sesiunea a fost deja trimisă la transcriere
        // (de ex. de Session Watcher, după o pană lungă de rețea)
        if (status === 409 && !detail.includes('Reîncearcă')) {
          patch({ phase: 'done', recordingId: sessionId })
          return
        }
        if ((status !== undefined && status < 500 && status !== 409) || attempt >= COMPLETE_ATTEMPTS) {
          patch({
            phase: 'error',
            recordingId: sessionId,
            error: (detail || 'Nu am putut porni transcrierea.')
              + ' Segmentele trimise sunt pe server; sesiunea pornește automat la transcriere după 30 de minute.',
          })
          return
        }
        await sleep(COMPLETE_RETRY_MS)
      }
    }
  }, [enqueueSegment, patch, releaseMicrophone])
  stopRef.current = stop

  const reset = useCallback(() => {
    if (recordingRef.current) return
    uploaderRef.current?.stop()
    uploaderRef.current = null
    sessionRef.current = null
    releaseMicrophone()
    setState(INITIAL)
  }, [releaseMicrophone])

  // Nivelul și durata, actualizate de câteva ori pe secundă (nu la fiecare bloc audio)
  const live = state.phase === 'ready' || state.phase === 'recording'
  useEffect(() => {
    if (!live) return
    const id = setInterval(() => {
      patch({ level: levelRef.current, elapsedSeconds: samplesRef.current / TARGET_SAMPLE_RATE })
    }, UI_TICK_MS)
    return () => clearInterval(id)
  }, [live, patch])

  const busy = state.phase === 'starting' || state.phase === 'recording' || state.phase === 'finishing'
    || state.upload.pending > 0

  // Avertisment la închiderea / reîncărcarea paginii în timpul înregistrării
  useEffect(() => {
    if (!busy) return
    const onBeforeUnload = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = '' }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [busy])

  // Wake lock-ul se pierde când fereastra e ascunsă; îl cerem din nou la revenire
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible' && recordingRef.current) void acquireWakeLock()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [acquireWakeLock])

  // Microfon nou conectat / deconectat: actualizăm lista
  useEffect(() => {
    if (state.devices.length === 0 || !navigator.mediaDevices) return
    const onChange = () => { void listDevices().then(devices => patch({ devices })) }
    navigator.mediaDevices.addEventListener('devicechange', onChange)
    return () => navigator.mediaDevices.removeEventListener('devicechange', onChange)
  }, [state.devices.length, listDevices, patch])

  // La deconectare (provider demontat): eliberăm microfonul
  useEffect(() => () => {
    recordingRef.current = false
    uploaderRef.current?.stop()
    if (refreshTimerRef.current) clearInterval(refreshTimerRef.current)
    streamRef.current?.getTracks().forEach(t => t.stop())
    void ctxRef.current?.close().catch(() => {})
  }, [])

  return (
    <RecorderContext.Provider value={{
      ...state, supported: isRecordingSupported(), busy, enableMicrophone, start, stop, reset,
    }}>
      {children}
    </RecorderContext.Provider>
  )
}

export function useRecorder(): RecorderContextType {
  const ctx = useContext(RecorderContext)
  if (!ctx) throw new Error('useRecorder trebuie folosit în <RecorderProvider>')
  return ctx
}
