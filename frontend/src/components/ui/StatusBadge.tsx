import { cn } from '@/lib/cn'

const statusConfig: Record<string, { label: string; className: string; dot?: string }> = {
  uploaded:    { label: 'Încărcat',      className: 'bg-blue-50 text-blue-700 ring-blue-600/20' },
  validating:  { label: 'Validare...',   className: 'bg-violet-50 text-violet-700 ring-violet-600/20',  dot: 'bg-violet-500' },
  queued:      { label: 'În coadă',      className: 'bg-amber-50 text-amber-700 ring-amber-600/20',     dot: 'bg-amber-500' },
  transcribing:{ label: 'Transcriere',   className: 'bg-blue-50 text-blue-700 ring-blue-600/20',        dot: 'bg-blue-500' },
  completed:   { label: 'Finalizat',     className: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20' },
  failed:      { label: 'Eșuat',         className: 'bg-rose-50 text-rose-700 ring-rose-600/20' },
  archived:    { label: 'Arhivat',       className: 'bg-slate-100 text-slate-600 ring-slate-500/20' },
  pending:     { label: 'În așteptare',  className: 'bg-amber-50 text-amber-700 ring-amber-600/20',     dot: 'bg-amber-500' },
  processing:  { label: 'Procesare',     className: 'bg-blue-50 text-blue-700 ring-blue-600/20',        dot: 'bg-blue-500' },
}

export function StatusBadge({ status }: { status: string }) {
  const cfg = statusConfig[status] ?? { label: status, className: 'bg-slate-100 text-slate-600 ring-slate-500/20' }

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ring-1 ring-inset',
        cfg.className
      )}
      aria-label={`Stare: ${cfg.label}`}
    >
      {cfg.dot && (
        <span
          className={cn('h-1.5 w-1.5 rounded-full animate-pulse', cfg.dot)}
          aria-hidden="true"
        />
      )}
      {cfg.label}
    </span>
  )
}
