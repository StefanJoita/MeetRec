import { cn } from '@/lib/cn'

function SkeletonBox({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn('bg-gray-200 rounded animate-pulse', className)}
    />
  )
}

/** Skeleton pentru tabel (RecordingsListPage, AdminPage) */
export function SkeletonTable({ rows = 8, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div className="card overflow-hidden" aria-label="Se încarcă..." aria-busy="true">
      <table className="min-w-full">
        <thead className="bg-gray-50">
          <tr>
            {Array.from({ length: cols }).map((_, i) => (
              <th key={i} className="px-4 py-3">
                <SkeletonBox className="h-3 w-20 rounded" />
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-50">
          {Array.from({ length: rows }).map((_, i) => (
            <tr key={i}>
              {Array.from({ length: cols }).map((_, j) => (
                <td key={j} className="px-4 py-3">
                  <SkeletonBox
                    className={cn('h-4 rounded', j === 0 ? 'w-48' : j === cols - 1 ? 'w-16' : 'w-24')}
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Skeleton pentru pagina de detaliu înregistrare */
export function SkeletonCard() {
  return (
    <div className="p-6 max-w-5xl mx-auto" aria-label="Se încarcă..." aria-busy="true">
      {/* Header */}
      <SkeletonBox className="h-4 w-20 mb-6" />
      <div className="flex justify-between mb-6">
        <div className="space-y-2 flex-1">
          <SkeletonBox className="h-4 w-24" />
          <SkeletonBox className="h-7 w-80" />
          <SkeletonBox className="h-4 w-56" />
        </div>
        <div className="flex gap-2">
          <SkeletonBox className="h-9 w-20 rounded-lg" />
          <SkeletonBox className="h-9 w-9 rounded-lg" />
        </div>
      </div>
      {/* Meta grid */}
      <div className="grid grid-cols-4 gap-3 mb-6">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="bg-gray-50 rounded-xl p-3 space-y-2">
            <SkeletonBox className="h-3 w-16" />
            <SkeletonBox className="h-4 w-20" />
          </div>
        ))}
      </div>
      {/* Player */}
      <SkeletonBox className="h-16 rounded-xl mb-6" />
      {/* Transcript */}
      <div className="card overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100">
          <SkeletonBox className="h-4 w-24" />
        </div>
        <div className="p-4 space-y-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex gap-3">
              <SkeletonBox className="h-4 w-12 shrink-0" />
              <SkeletonBox className={cn('h-4 rounded', i % 3 === 0 ? 'w-full' : i % 3 === 1 ? 'w-3/4' : 'w-5/6')} />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

/** Skeleton pentru rezultate căutare */
export function SkeletonSearchResults() {
  return (
    <div className="space-y-3" aria-label="Se încarcă..." aria-busy="true">
      {Array.from({ length: 3 }).map((_, i) => (
        <div key={i} className="card p-4 space-y-2">
          <div className="flex justify-between">
            <SkeletonBox className="h-4 w-48" />
            <SkeletonBox className="h-4 w-20" />
          </div>
          <SkeletonBox className="h-3 w-full" />
          <SkeletonBox className="h-3 w-4/5" />
          <SkeletonBox className="h-3 w-16 mt-1" />
        </div>
      ))}
    </div>
  )
}
