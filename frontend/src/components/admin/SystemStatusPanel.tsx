import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { AlertTriangle, Archive, Cpu, HardDrive, ListOrdered, Loader2, Search, Server } from 'lucide-react'
import { getSystemStatus, runBackupNow, type BackupStatus, type SystemStatus } from '@/api/admin'
import { SkeletonTable } from '@/components/ui/Skeleton'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { useToast } from '@/contexts/ToastContext'

function formatBytes(bytes: number): string {
  const gb = bytes / 1024 ** 3
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${(bytes / 1024 ** 2).toFixed(0)} MB`
}

function secondsAgo(epochSeconds: number): string {
  const s = Math.max(0, Math.round(Date.now() / 1000 - epochSeconds))
  if (s < 60) return `acum ${s} s`
  return `acum ${Math.round(s / 60)} min`
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString('ro-RO', { dateStyle: 'medium', timeStyle: 'short' })
}

// Un backup reușit mai vechi de atât (ore) e semnalat: backup-ul zilnic nu mai rulează
const STALE_BACKUP_HOURS = 36

function BackupCard({ backup }: { backup: BackupStatus }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const run = useMutation({
    mutationFn: runBackupNow,
    onSuccess: () => {
      toast('Backup-ul pornește în cel mult 30 de secunde.', 'success')
      queryClient.invalidateQueries({ queryKey: ['admin-system'] })
    },
    onError: (error) => {
      const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
      toast(typeof detail === 'string' ? detail : 'Nu am putut porni backup-ul.', 'error')
    },
  })
  const { last } = backup
  const running = last?.state === 'running' || backup.requested
  const lastSuccess = last?.state === 'ok' ? last.finished_at : last?.last_success_at
  const stale = lastSuccess
    ? Date.now() - new Date(lastSuccess).getTime() > STALE_BACKUP_HOURS * 3600_000
    : true

  return (
    <Card icon={<Archive className="h-4 w-4 text-teal-600" />} title="Backup">
      {running ? (
        <p className="text-sm text-blue-700 flex items-center gap-1.5">
          <Loader2 className="h-4 w-4 animate-spin" />
          {last?.state === 'running' ? 'Backup în curs…' : 'Backup cerut, pornește în curând…'}
        </p>
      ) : last?.state === 'failed' ? (
        <p className="text-sm text-red-600 flex items-start gap-1.5">
          <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
          <span>Ultimul backup a eșuat{last.finished_at ? ` (${formatDateTime(last.finished_at)})` : ''}: {last.error}</span>
        </p>
      ) : last?.state === 'ok' && last.finished_at ? (
        <p className="text-sm text-gray-900">Ultimul backup: {formatDateTime(last.finished_at)}</p>
      ) : (
        <p className="text-sm text-gray-500">Niciun backup încă.</p>
      )}

      {last?.state === 'ok' && (
        <p className="text-xs text-gray-500 mt-1">
          Bază de date {formatBytes(last.db_bytes ?? 0)} · {last.audio_files ?? 0} fișiere audio
          ({formatBytes(last.audio_bytes ?? 0)}), {last.audio_copied ?? 0} noi
          {last.free_bytes !== undefined && <> · liber la destinație {formatBytes(last.free_bytes)}</>}
        </p>
      )}
      {last?.state === 'failed' && last.last_success_at && (
        <p className="text-xs text-gray-500 mt-1">Ultimul backup reușit: {formatDateTime(last.last_success_at)}</p>
      )}
      {backup.enabled === false ? (
        <p className="text-xs text-amber-700 mt-1">Backup-ul zilnic e oprit (Administrare → Setări).</p>
      ) : stale && !running && (
        <p className="text-xs text-amber-700 mt-1">Niciun backup reușit în ultimele {STALE_BACKUP_HOURS} de ore.</p>
      )}
      {backup.path && <p className="text-xs text-gray-400 mt-1">Destinație: {backup.path}</p>}

      <button
        type="button"
        className="btn-secondary mt-3"
        disabled={running || run.isPending}
        onClick={() => run.mutate()}
      >
        Backup acum
      </button>
    </Card>
  )
}

function Card({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <section className="card-padded">
      <div className="flex items-center gap-2 mb-3">
        {icon}
        <h2 className="text-sm font-semibold text-gray-700">{title}</h2>
      </div>
      {children}
    </section>
  )
}

export default function SystemStatusPanel() {
  const { data, isLoading, isError } = useQuery<SystemStatus>({
    queryKey: ['admin-system'],
    queryFn: getSystemStatus,
    refetchInterval: 15_000,
    retry: false,
  })

  if (isLoading) return <SkeletonTable rows={6} cols={3} />
  if (isError || !data) {
    return <div className="card-padded text-sm text-red-600">Nu am putut încărca starea sistemului.</div>
  }

  const { queue, disk } = data
  const diskFreePct = disk ? (disk.free_bytes / disk.total_bytes) * 100 : null

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <Card icon={<Server className="h-4 w-4 text-blue-600" />} title="Versiune">
        <dl className="text-sm grid grid-cols-2 gap-y-1">
          <dt className="text-gray-500">MeetRec</dt>
          <dd className="text-gray-900">{data.version ?? '—'}</dd>
          <dt className="text-gray-500">Model Whisper (.env)</dt>
          <dd className="text-gray-900">{data.whisper_model_configured ?? '—'}</dd>
        </dl>
      </Card>

      <Card icon={<ListOrdered className="h-4 w-4 text-amber-600" />} title="Coadă de transcriere">
        {queue.available ? (
          <div className="flex gap-8">
            <div>
              <p className="text-2xl font-bold text-gray-900">{queue.queued}</p>
              <p className="text-xs text-gray-500">în așteptare</p>
            </div>
            <div>
              <p className="text-2xl font-bold text-gray-900">{queue.processing}</p>
              <p className="text-xs text-gray-500">în lucru</p>
            </div>
          </div>
        ) : (
          <p className="text-sm text-red-600">Redis nu răspunde — coada nu poate fi citită.</p>
        )}
      </Card>

      <Card icon={<Cpu className="h-4 w-4 text-violet-600" />} title="Worker de transcriere">
        {queue.workers.length === 0 ? (
          <p className="text-sm text-red-600 flex items-center gap-1.5">
            <AlertTriangle className="h-4 w-4" />
            Niciun worker activ. Dacă tocmai a repornit, încarcă modelele (1-3 minute).
          </p>
        ) : (
          <ul className="space-y-3">
            {queue.workers.map(w => (
              <li key={w.worker_id} className="text-sm">
                <div className="flex items-center justify-between">
                  <span className="font-medium text-gray-900">{w.worker_id}</span>
                  <span className="text-xs text-gray-400">semnal {secondsAgo(w.updated_at)}</span>
                </div>
                <p className="text-xs text-gray-500 mt-0.5">
                  {w.whisper_model} · {w.whisper_threads} fire ·{' '}
                  diarizare {w.diarization_enabled ? (w.diarization_parallel ? 'în paralel' : 'succesivă') : 'oprită'}
                </p>
                <p className="text-xs mt-0.5">
                  {w.current_recording_id ? (
                    <Link to={`/recordings/${w.current_recording_id}`} className="text-blue-600 hover:underline">
                      Transcrie acum o înregistrare
                    </Link>
                  ) : (
                    <span className="text-green-700">Liber</span>
                  )}
                </p>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card icon={<Search className="h-4 w-4 text-sky-600" />} title="Căutare după sens">
        {data.search_index.available ? (
          <>
            <p className="text-sm text-gray-900">
              {data.search_index.pending_segments === 0
                ? 'Toate transcrierile sunt indexate.'
                : `${data.search_index.pending_segments ?? '?'} fragmente în curs de indexare.`}
            </p>
            <p className="text-xs text-gray-500 mt-1">Model: {data.search_index.model ?? '—'}</p>
          </>
        ) : (
          <p className="text-sm text-red-600">
            Serviciul de indexare nu răspunde — căutarea funcționează doar cu potriviri exacte.
          </p>
        )}
      </Card>

      <Card icon={<HardDrive className="h-4 w-4 text-slate-600" />} title="Spațiu pentru înregistrări">
        {disk && diskFreePct !== null ? (
          <>
            <div className="h-2 rounded-full bg-gray-100 overflow-hidden">
              <div
                className={`h-full ${diskFreePct < 10 ? 'bg-red-500' : diskFreePct < 25 ? 'bg-amber-500' : 'bg-blue-500'}`}
                style={{ width: `${100 - diskFreePct}%` }}
              />
            </div>
            <p className="text-xs text-gray-500 mt-2">
              Liber {formatBytes(disk.free_bytes)} din {formatBytes(disk.total_bytes)} ({diskFreePct.toFixed(0)}%)
            </p>
            {diskFreePct < 10 && (
              <p className="text-xs text-red-600 mt-1">Spațiu aproape epuizat — încărcările și transcrierile pot eșua.</p>
            )}
          </>
        ) : (
          <p className="text-sm text-gray-500">Indisponibil.</p>
        )}
      </Card>

      <BackupCard backup={data.backup} />

      <Card icon={<ListOrdered className="h-4 w-4 text-emerald-600" />} title="Înregistrări pe stări">
        {Object.keys(data.recordings_by_status).length === 0 ? (
          <p className="text-sm text-gray-500">Nicio înregistrare.</p>
        ) : (
          <div className="flex flex-wrap gap-3">
            {Object.entries(data.recordings_by_status).map(([status, count]) => (
              <div key={status} className="flex items-center gap-1.5">
                <StatusBadge status={status} />
                <span className="text-sm font-medium text-gray-900">{count}</span>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card icon={<AlertTriangle className="h-4 w-4 text-rose-600" />} title="Eșecuri recente">
        {data.recent_failures.length === 0 ? (
          <p className="text-sm text-gray-500">Niciun eșec.</p>
        ) : (
          <ul className="space-y-2">
            {data.recent_failures.map(f => (
              <li key={f.id} className="text-sm">
                <Link to={`/recordings/${f.id}`} className="font-medium text-blue-600 hover:underline">{f.title}</Link>
                {f.error_message && <p className="text-xs text-gray-500 line-clamp-2">{f.error_message}</p>}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
