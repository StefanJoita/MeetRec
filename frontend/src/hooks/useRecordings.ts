// frontend/src/hooks/useRecordings.ts
// Hook pentru lista paginată de înregistrări cu filtrare și sortare.

import { useQuery } from '@tanstack/react-query'
import { getRecordings } from '@/api/recordings'
import type { PaginatedRecordings } from '@/api/types'

interface UseRecordingsParams {
  page?: number
  page_size?: number
  status?: string
  search?: string
  sort_by?: string
  sort_desc?: boolean
}

export function useRecordings(params: UseRecordingsParams = {}) {
  const {
    page = 1,
    page_size = 20,
    status,
    search,
    sort_by = 'created_at',
    sort_desc = true,
  } = params

  return useQuery<PaginatedRecordings>({
    queryKey: ['recordings', page, page_size, status, search, sort_by, sort_desc],
    queryFn: () =>
      getRecordings({
        page,
        page_size,
        status: status || undefined,
        search: search || undefined,
        sort_by,
        sort_desc,
      }),
    // Păstrăm datele anterioare la schimbarea paginii (no flash)
    placeholderData: (prev) => prev,
  })
}
