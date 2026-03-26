import { ChevronLeft, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/cn'

interface PaginationProps {
  page: number
  pages: number
  total?: number
  onPageChange: (page: number) => void
  className?: string
}

function pageRange(current: number, total: number): (number | '…')[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1)
  const delta = 1
  const left  = current - delta
  const right = current + delta
  const pages: (number | '…')[] = []

  if (left > 2) {
    pages.push(1, '…')
  } else {
    for (let i = 1; i < left; i++) pages.push(i)
  }

  for (let i = Math.max(1, left); i <= Math.min(total, right); i++) pages.push(i)

  if (right < total - 1) {
    pages.push('…', total)
  } else {
    for (let i = right + 1; i <= total; i++) pages.push(i)
  }

  return pages
}

export function Pagination({ page, pages, total, onPageChange, className = '' }: PaginationProps) {
  if (pages <= 1) return null

  const range = pageRange(page, pages)

  return (
    <div className={cn('flex items-center justify-between', className)}>
      <p className="text-sm text-slate-500 hidden sm:block">
        Pagina {page} din {pages}{total != null ? ` · ${total} înregistrări` : ''}
      </p>

      <div className="flex items-center gap-1 mx-auto sm:mx-0">
        <button
          onClick={() => onPageChange(Math.max(1, page - 1))}
          disabled={page === 1}
          aria-label="Pagina anterioară"
          className="p-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>

        {range.map((p, i) =>
          p === '…' ? (
            <span key={`ellipsis-${i}`} className="w-8 text-center text-slate-400 text-sm select-none">
              …
            </span>
          ) : (
            <button
              key={p}
              onClick={() => onPageChange(p as number)}
              aria-current={p === page ? 'page' : undefined}
              className={cn(
                'w-8 h-8 rounded-lg text-sm font-medium transition-colors',
                p === page
                  ? 'bg-primary-600 text-white shadow-sm'
                  : 'text-slate-600 hover:bg-slate-100 border border-transparent hover:border-slate-200',
              )}
            >
              {p}
            </button>
          )
        )}

        <button
          onClick={() => onPageChange(Math.min(pages, page + 1))}
          disabled={page === pages}
          aria-label="Pagina următoare"
          className="p-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  )
}
