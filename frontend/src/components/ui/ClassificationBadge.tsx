import { cn } from '@/lib/cn'
import { classificationLevel } from '@/lib/classification'

/** Nivelul de clasificare: denumirea completă (implicit) sau doar codul (N, SSv, S, SS). */
export function ClassificationBadge({ code, short, className }: { code: string; short?: boolean; className?: string }) {
  const level = classificationLevel(code)
  return (
    <span
      className={cn(
        'inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium ring-1 ring-inset whitespace-nowrap',
        level.badge,
        className,
      )}
      title={short ? level.label : undefined}
      aria-label={`Clasificare: ${level.label}`}
    >
      {short ? level.code : level.label}
    </span>
  )
}
