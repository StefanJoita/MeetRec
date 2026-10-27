import { cn } from '@/lib/cn'

/** Marchează o funcție nouă, încă în testare (ex. înregistrarea din browser). */
export function BetaBadge({ className, onDark = false }: { className?: string; onDark?: boolean }) {
  return (
    <span
      className={cn(
        'inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide leading-none',
        onDark ? 'bg-amber-400/20 text-amber-300' : 'bg-amber-100 text-amber-800 ring-1 ring-inset ring-amber-600/20',
        className
      )}
      title="Funcție nouă, în testare"
    >
      Beta
    </span>
  )
}
