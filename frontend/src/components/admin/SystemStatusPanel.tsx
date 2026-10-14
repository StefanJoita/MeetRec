import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { AlertTriangle, Cpu, HardDrive, ListOrdered, Server } from 'lucide-react'
import { getSystemStatus, type SystemStatus } from '@/api/admin'
import { SkeletonTable } from '@/components/ui/Skeleton'
import { StatusBadge } from '@/components/ui/StatusBadge'

function formatBytes(bytes: number): string {
  const gb = bytes / 1024 ** 3
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${(bytes / 1024 ** 2).toFixed(0)} MB`
}

function secondsAgo(epochSeconds: number): string {
  const s = Math.max(0, Math.round(Date.now() / 1000 - epochSeconds))
  if (s < 60) return `acum ${s} s`
  return `acum ${Math.round(s / 60)} min`
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
