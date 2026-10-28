import { useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, CheckCircle, Circle, Mic, Square } from 'lucide-react'
import { useRecorder } from '@/contexts/RecorderContext'
import type { SessionMetadata } from '@/api/recordingSession'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { Spinner } from '@/components/ui/Spinner'
import { formatTime } from '@/lib/formatTime'
import { cn } from '@/lib/cn'

/** Nivelul microfonului: bara trebuie să se miște când se vorbește. */
export function LevelMeter({ level }: { level: number }) {
  const pct = Math.round(level * 100)
  return (
    <div className="h-2 bg-slate-200 rounded-full overflow-hidden" role="meter" aria-label="Nivel microfon"
         aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
      <div
        className={cn('h-2 rounded-full transition-[width] duration-150',
          level > 0.9 ? 'bg-rose-500' : level > 0.05 ? 'bg-green-500' : 'bg-slate-400')}
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}

interface Props {
  /** Detaliile ședinței din formular, citite la pornire. */
  getMetadata: () => SessionMetadata
  onNewRecording: () => void
  /** Motivul pentru care înregistrarea nu poate porni încă (ex. nivelul de clasificare nu e ales). */
  startBlocked?: string
}

export default function LiveRecorder({ getMetadata, onNewRecording, startBlocked }: Props) {
  const rec = useRecorder()
  const [confirmStop, setConfirmStop] = useState(false)

  if (!rec.supported) {
    return (
      <div className="border border-amber-200 bg-amber-50 rounded-xl p-5 text-sm text-amber-800 space-y-2">
        <p className="font-medium flex items-center gap-2"><AlertTriangle className="h-4 w-4" /> Microfonul nu e disponibil</p>
        <p>
          Browserul permite înregistrarea doar pe o conexiune securizată. Deschideți aplicația cu adresa
          {' '}<strong>https://</strong> și, dacă browserul afișează un avertisment de certificat, importați
          certificatul CA al serverului (<code>meetrec-ca.crt</code>), conform manualului de instalare.
        </p>
      </div>
    )
  }

  if (rec.phase === 'done') {
    return (
      <div className="border border-slate-200 rounded-xl p-8 text-center">
        <CheckCircle className="h-12 w-12 text-green-500 mx-auto mb-3" />
        <h2 className="text-lg font-semibold text-gray-900 mb-1">Înregistrarea a fost trimisă la transcriere</h2>
        <p className="text-sm text-gray-500 mb-1">{rec.title} · {formatTime(rec.elapsedSeconds)}</p>
        {rec.upload.failed > 0 && (
          <p className="text-sm text-amber-700 mb-1">{rec.upload.failed} segment(e) au fost respinse de server.</p>
        )}
        {rec.warning && <p className="text-sm text-amber-700 mb-1">{rec.warning}</p>}
        <div className="flex gap-3 justify-center mt-5">
          {rec.recordingId && (
            <Link to={`/recordings/${rec.recordingId}`} className="btn-primary">Deschide înregistrarea</Link>
          )}
          <button type="button" onClick={onNewRecording} className="btn-secondary">Înregistrare nouă</button>
        </div>
      </div>
    )
  }

  const recording = rec.phase === 'recording'
  const finishing = rec.phase === 'finishing'

  if (recording || finishing) {
    return (
      <div className="border-2 border-rose-200 bg-rose-50/40 rounded-xl p-6 space-y-5">
        <div className="flex items-center justify-between gap-4">
          <div className="min-w-0">
            <p className="text-xs font-medium text-rose-600 uppercase tracking-wide flex items-center gap-2">
              {recording
                ? <><span className="h-2.5 w-2.5 rounded-full bg-rose-600 animate-pulse" /> Se înregistrează</>
                : <><Spinner className="h-3 w-3" /> Se finalizează</>}
            </p>
            <p className="text-sm font-medium text-gray-900 truncate mt-1">{rec.title}</p>
          </div>
          <p className="text-3xl font-semibold tabular-nums text-gray-900" aria-label="Durata înregistrării">
            {formatTime(rec.elapsedSeconds)}
          </p>
        </div>

        {recording && <LevelMeter level={rec.level} />}

        <div className="text-xs text-gray-600 space-y-1">
          <p>
            Segmente trimise: <strong>{rec.upload.uploaded}</strong>
            {rec.upload.pending > 0 && <> · în așteptare: <strong>{rec.upload.pending}</strong></>}
            {rec.upload.failed > 0 && <span className="text-rose-600"> · respinse: {rec.upload.failed}</span>}
          </p>
          {recording && (
            <p className="text-gray-500">
              Audio-ul pleacă la server la fiecare 5 minute. Puteți folosi aplicația în continuare;
              nu închideți fereastra și nu lăsați calculatorul să intre în repaus.
            </p>
          )}
          {finishing && (
            <p className="text-gray-500">
              {rec.upload.pending > 0
                ? 'Se trimit ultimele segmente. Nu închideți pagina.'
                : 'Se pornește transcrierea…'}
            </p>
          )}
        </div>

        {(rec.upload.retrying || rec.upload.lastError) && (
          <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
            {rec.upload.lastError}
          </p>
        )}
        {rec.warning && (
          <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">{rec.warning}</p>
        )}

        {recording && (
          <button type="button" onClick={() => setConfirmStop(true)} className="btn-danger w-full justify-center">
            <Square className="h-4 w-4 fill-current" /> Oprește și trimite la transcriere
          </button>
        )}

        <ConfirmDialog
          open={confirmStop}
          title="Opriți înregistrarea?"
          description="Înregistrarea se încheie și pornește transcrierea. O ședință oprită nu mai poate fi continuată."
          confirmLabel="Oprește"
          danger
          onConfirm={() => { setConfirmStop(false); void rec.stop() }}
          onClose={() => setConfirmStop(false)}
        />
      </div>
    )
  }

  const ready = rec.phase === 'ready' || rec.phase === 'starting'
  return (
    <div className="border border-slate-200 rounded-xl p-6 space-y-4">
      {rec.error && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
          {rec.error}
          {rec.recordingId && (
            <Link to={`/recordings/${rec.recordingId}`} className="ml-1 font-medium underline">Deschide înregistrarea</Link>
          )}
        </div>
      )}

      {!ready ? (
        <div className="text-center py-4">
          <Mic className="h-10 w-10 text-gray-300 mx-auto mb-3" />
          <p className="text-sm text-gray-600 mb-4">
            Folosiți microfonul conectat la acest calculator: microfon de conferință USB, placă de sunet
            legată la sistemul de sonorizare al sălii sau microfonul laptopului.
          </p>
          <button
            type="button"
            onClick={() => void rec.enableMicrophone()}
            disabled={rec.phase === 'requesting'}
            className="btn-secondary"
          >
            {rec.phase === 'requesting' ? <><Spinner className="h-4 w-4" /> Se cere accesul…</> : <><Mic className="h-4 w-4" /> Activează microfonul</>}
          </button>
        </div>
      ) : (
        <>
          <div>
            <label htmlFor="microphone" className="block text-xs font-medium text-gray-600 mb-1">Microfon</label>
            <select
              id="microphone"
              value={rec.deviceId}
              onChange={(e) => void rec.enableMicrophone(e.target.value)}
              disabled={rec.phase === 'starting'}
              className="input-base w-full"
            >
              {rec.devices.map(d => <option key={d.deviceId} value={d.deviceId}>{d.label}</option>)}
            </select>
          </div>
          <div>
            <p className="text-xs text-gray-500 mb-1.5">Vorbiți: bara trebuie să se miște. Dacă rămâne gri, alegeți alt microfon.</p>
            <LevelMeter level={rec.level} />
          </div>
          <button
            type="button"
            onClick={() => void rec.start(getMetadata())}
            disabled={rec.phase === 'starting' || !!startBlocked}
            className="btn-danger w-full justify-center"
          >
            {rec.phase === 'starting'
              ? <><Spinner className="h-4 w-4" /> Se pornește…</>
              : startBlocked ?? <><Circle className="h-4 w-4 fill-current" /> Pornește înregistrarea</>}
          </button>
        </>
      )}
    </div>
  )
}
