// frontend/src/hooks/useSearch.ts
// Hook pentru full-text search în transcrieri, cu paginare.

import { useState, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { search as apiSearch } from '@/api/search'
import type { SearchResponse } from '@/api/types'

interface UseSearchOptions {
  limit?: number
}

export function useSearch(options: UseSearchOptions = {}) {
  const { limit = 20 } = options

  const [query, setQuery] = useState('')
  const [committedQuery, setCommittedQuery] = useState('')
  const [offset, setOffset] = useState(0)

  const result = useQuery<SearchResponse>({
    queryKey: ['search', committedQuery, offset, limit],
    queryFn: () => apiSearch(committedQuery, { limit, offset }),
    enabled: committedQuery.length >= 2,
    // Păstrăm rezultatele anterioare la schimbarea paginii
    placeholderData: (prev) => prev,
  })

  const submit = useCallback(() => {
    const q = query.trim()
    if (q.length < 2) return
    setOffset(0)
    setCommittedQuery(q)
  }, [query])

  const nextPage = useCallback(() => {
    setOffset((o) => o + limit)
  }, [limit])

  const prevPage = useCallback(() => {
    setOffset((o) => Math.max(0, o - limit))
  }, [limit])

  const currentPage = Math.floor(offset / limit) + 1

  return {
    // State
    query,
    setQuery,
    // Acțiuni
    submit,
    nextPage,
    prevPage,
    // Paginare
    currentPage,
    offset,
    // Query result
    ...result,
  }
}
