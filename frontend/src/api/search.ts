import client from './client'
import type { SearchResponse, CombinedSearchResponse } from './types'

interface SearchParams {
  limit?: number
  offset?: number
  language?: string
}

export interface SearchFilters {
  date_from?: string      // YYYY-MM-DD
  date_to?: string        // YYYY-MM-DD
  location?: string
  min_duration?: number   // secunde
}

export async function search(q: string, params: SearchParams = {}): Promise<SearchResponse> {
  const { data } = await client.get<SearchResponse>('/search', {
    params: { q, limit: params.limit ?? 20, offset: params.offset ?? 0, language: params.language },
  })
  return data
}

export async function searchCombined(
  q: string,
  limit = 20,
  filters: SearchFilters = {},
): Promise<CombinedSearchResponse> {
  const { data } = await client.get<CombinedSearchResponse>('/search/combined', {
    params: {
      q,
      limit,
      ...(filters.date_from    ? { date_from:    filters.date_from }    : {}),
      ...(filters.date_to      ? { date_to:      filters.date_to }      : {}),
      ...(filters.location     ? { location:     filters.location }     : {}),
      ...(filters.min_duration ? { min_duration: filters.min_duration } : {}),
    },
  })
  return data
}
