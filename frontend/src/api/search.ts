import client from './client'
import type { SearchResponse } from './types'

export async function search(q: string, limit = 20): Promise<SearchResponse> {
  const { data } = await client.get<SearchResponse>('/search', { params: { q, limit } })
  return data
}
