import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { AlertTriangle, ArrowUpToLine, Cpu, ListOrdered, Square, X } from 'lucide-react'
import {
  cancelTranscription, getQueue, prioritizeTranscription,
  type QueueItem, type RunningQueueItem, type TranscriptionQueue,
} from '@/api/admin'
import { SkeletonTable } from '@/components/ui/Skeleton'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { useToast } from '@/contexts/ToastContext'
import { formatDuration } from '@/components/admin/ProcessingPanel'

const STAGES = [
  ['transcriere', 'Transcriere'],
  ['aliniere', 'Aliniere'],
  ['diarizare', 'Diarizare'],
] as const

const TH = 'px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider'

function errorDetail(error: unknown, fallback: string): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof detail === 'string' ? detail : fallback
}

function Title({ item }: { item: QueueItem }) {
  if (item.title === null) return <span className="text-gray-400 italic">Înregistrare ștearsă</span>
  return (
    <Link to={`/recordings/${item.recording_id}`} className="text-blue-600 hover:underline">
      {item.title}
    </Link>
  )
}

function StageProgress({ progress }: { progress: Record<string, number> }) {
  const stages = STAGES.filter(([key]) => progress[key] !== undefined)
  if (stages.length === 0) return <p className="text-xs text-gray-400">Pregătire (detectarea limbii, încărcarea audio)…</p>
  return (
    <div className="space-y-1.5">
      {stages.map(([key, label]) => (
        <div key={key} className="flex items-center gap-2 text-xs">
          <span className="w-20 text-gray-500">{label}</span>
          <div
            className="flex-1 h-1.5 rounded-full bg-gray-100 overflow-hidden"
            role="progressbar" aria-label={label} aria-valuenow={progress[key]} aria-valuemin={0} aria-valuemax={100}
          >
            <div className="h-full bg-blue-500" style={{ width: `${progress[key]}%` }} />
          </div>
          <span className="w-9 text-right tabular-nums text-gray-600">{progress[key]}%</span>
        </div>
      ))}
    </div>
  )
}

type Pending = { action: 'stop' | 'remove'; item: QueueItem } | null

export default function QueuePanel() {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [pending, setPending] = useState<Pending>(null)

  const { data, isLoading, isError } = useQuery<TranscriptionQueue>({
    queryKey: ['admin-queue'],
    queryFn: getQueue,
    refetchInterval: 3_000,
    retry: false,
  })

  function refresh() {
    queryClient.invalidateQueries({ queryKey: ['admin-queue'] })
    queryClient.invalidateQueries({ queryKey: ['recordings'] })
  }

  const cancelMutation = useMutation({
    mutationFn: (item: QueueItem) => cancelTranscription(item.recording_id),
    onSuccess: (result) => {
      toast(result.running
        ? 'Transcrierea se oprește în câteva secunde.'
        : 'Înregistrarea a fost scoasă din coadă.', 'success')
      refresh()
    },
    onError: (error) => toast(errorDetail(error, 'Nu am putut anula transcrierea.'), 'error'),
  })

  const prioritizeMutation = useMutation({
    mutationFn: (item: QueueItem) => prioritizeTranscription(item.recording_id),
    onSuccess: () => { toast('Înregistrarea va fi transcrisă următoarea.', 'success'); refresh() },
    onError: (error) => toast(errorDetail(error, 'Nu am putut muta înregistrarea.'), 'error'),
  })

  if (isLoading) return <SkeletonTable rows={6} cols={4} />
  if (isError || !data) {
    return <div className="card-padded text-sm text-red-600">Nu am putut încărca coada de transcriere.</div>
  }
  if (!data.available) {
    return <div className="card-padded text-sm text-red-600">Redis nu răspunde — coada nu poate fi citită.</div>
  }

  const busy = cancelMutation.isPending || prioritizeMutation.isPending

  return (
    <div className="space-y-4">
      <section className="card-padded">
        <div className="flex items-center gap-2 mb-3">
          <Cpu className="h-4 w-4 text-violet-600" />
          <h2 className="text-sm font-semibold text-gray-700">În lucru</h2>
        </div>
        {data.running.length === 0 ? (
          <p className="text-sm text-gray-500">Nicio transcriere în curs.</p>
        ) : (
          <ul className="divide-y divide-gray-100">
            {data.running.map((item: RunningQueueItem) => {
              const stopping = item.cancelling || item.cancel_requested
              return (
                <li key={item.recording_id} className="py-3 first:pt-0 last:pb-0 flex flex-col sm:flex-row sm:items-start gap-3">
                  <div className="flex-1 min-w-0 space-y-2">
                    <div className="text-sm font-medium truncate"><Title item={item} /></div>
                    <p className="text-xs text-gray-500">
                      {formatDuration(item.duration_seconds)} audio · worker {item.worker_id}
                    </p>
                    {!item.worker_alive && (
                      <p className="text-xs text-amber-700 flex items-center gap-1.5">
                        <AlertTriangle className="h-3.5 w-3.5" />
                        Worker-ul nu răspunde. Dacă tocmai a repornit, reia jobul după încărcarea modelelor.
                      </p>
                    )}
                    {item.worker_alive && <StageProgress progress={item.progress} />}
                  </div>
                  {stopping ? (
                    <span className="text-xs font-medium text-amber-700 bg-amber-50 rounded-full px-2.5 py-1 self-start">
                      Se oprește…
                    </span>
                  ) : (
                    <button
                      className="btn-secondary text-sm self-start"
                      disabled={busy}
                      onClick={() => setPending({ action: 'stop', item })}
                    >
                      <Square className="h-4 w-4" />
                      Oprește
                    </button>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <section className="card overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100">
          <ListOrdered className="h-4 w-4 text-amber-600" />
          <h2 className="text-sm font-semibold text-gray-700">În așteptare ({data.waiting.length})</h2>
        </div>
        {data.waiting.length === 0 ? (
          <p className="px-4 py-6 text-sm text-gray-500">Coada e goală.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-100">
              <thead className="bg-gray-50">
                <tr>
                  <th className={TH}>#</th>
                  <th className={TH}>Înregistrare</th>
                  <th className={`${TH} hidden md:table-cell`}>Durată</th>
                  <th className={`${TH} hidden md:table-cell`}>Încărcată</th>
                  <th className={`${TH} text-right`}>Acțiuni</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data.waiting.map((item, index) => (
                  <tr key={item.recording_id}>
                    <td className="px-4 py-3 text-sm text-gray-500 tabular-nums">{index + 1}</td>
                    <td className="px-4 py-3 text-sm">
                      <Title item={item} />
                      {item.jobs > 1 && <span className="text-xs text-gray-400"> · {item.jobs} fișiere</span>}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600 hidden md:table-cell">
                      {formatDuration(item.duration_seconds)}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600 hidden md:table-cell">
                      {item.created_at ? new Date(item.created_at).toLocaleString('ro-RO') : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-2">
                        <button
                          className="btn-secondary text-sm"
                          disabled={busy || index === 0}
                          title={index === 0 ? 'Este deja următoarea' : 'Transcrie următoarea'}
                          onClick={() => prioritizeMutation.mutate(item)}
                        >
                          <ArrowUpToLine className="h-4 w-4" />
                          <span className="hidden sm:inline">Prima</span>
                        </button>
                        <button
                          className="btn-secondary text-sm"
                          disabled={busy}
                          onClick={() => setPending({ action: 'remove', item })}
                        >
                          <X className="h-4 w-4" />
                          <span className="hidden sm:inline">Scoate</span>
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <ConfirmDialog
        open={pending !== null}
        title={pending?.action === 'stop' ? 'Oprești transcrierea?' : 'Scoți înregistrarea din coadă?'}
        description={
          (pending?.action === 'stop'
            ? 'Transcrierea se oprește în câteva secunde, iar worker-ul trece la următorul fișier.'
            : 'Înregistrarea nu va mai fi transcrisă.')
          + (pending?.item.title !== null
            ? ' Înregistrarea rămâne, cu starea „Anulat”, și poate fi pornită din nou cu „Reîncearcă”.'
            : '')
        }
        confirmLabel={pending?.action === 'stop' ? 'Oprește' : 'Scoate din coadă'}
        cancelLabel="Înapoi"
        danger
        onConfirm={() => { if (pending) cancelMutation.mutate(pending.item); setPending(null) }}
        onClose={() => setPending(null)}
      />
    </div>
  )
}
