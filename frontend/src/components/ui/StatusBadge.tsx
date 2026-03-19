import { cn } from '@/lib/cn'

const statusConfig: Record<string, { label: string; className: string }> = {
  uploaded:    { label: 'Încărcat',     className: 'bg-blue-100 text-blue-700' },
  validating:  { label: 'Validare...',  className: 'bg-purple-100 text-purple-700' },
  queued:      { label: 'În coadă',     className: 'bg-yellow-100 text-yellow-700' },
  transcribing:{ label: 'Transcriere', className: 'bg-orange-100 text-orange-700' },
  completed:   { label: 'Finalizat',   className: 'bg-green-100 text-green-700' },
  failed:      { label: 'Eșuat',       className: 'bg-red-100 text-red-700' },
  archived:    { label: 'Arhivat',     className: 'bg-gray-100 text-gray-600' },
  // transcript statuses
  pending:     { label: 'În așteptare', className: 'bg-yellow-100 text-yellow-700' },
  processing:  { label: 'Procesare',   className: 'bg-orange-100 text-orange-700' },
}

export function StatusBadge({ status }: { status: string }) {
  const cfg = statusConfig[status] ?? { label: status, className: 'bg-gray-100 text-gray-600' }
  return (
    <span className={cn('inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium', cfg.className)}>
      {cfg.label}
    </span>
  )
}
