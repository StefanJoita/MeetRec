import client from './client'
import type { SearchResponse } from './types'

interface SearchParams {
  limit?: number
  offset?: number
  language?: string
}

export async function search(q: string, params: SearchParams = {}): Promise<SearchResponse> {
  const { data } = await client.get<SearchResponse>('/search', {
    params: { q, limit: params.limit ?? 20, offset: params.offset ?? 0, language: params.language },
  })
  return data
}
