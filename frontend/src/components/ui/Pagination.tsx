import { ChevronLeft, ChevronRight } from 'lucide-react'

interface PaginationProps {
  page: number
  pages: number
  total?: number
  onPageChange: (page: number) => void
  className?: string
}

export function Pagination({ page, pages, total, onPageChange, className = '' }: PaginationProps) {
  if (pages <= 1) return null

  return (
    <div className={`flex items-center justify-between ${className}`}>
      <p className="text-sm text-gray-500">
        Pagina {page} din {pages}{total != null ? ` · ${total} intrări` : ''}
      </p>
      <div className="flex gap-2">
        <button
          onClick={() => onPageChange(Math.max(1, page - 1))}
          disabled={page === 1}
          aria-label="Pagina anterioară"
          className="p-2 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <button
          onClick={() => onPageChange(Math.min(pages, page + 1))}
          disabled={page === pages}
          aria-label="Pagina următoare"
          className="p-2 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  )
}
