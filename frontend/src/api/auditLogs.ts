import client from '@/api/client'
import type { PaginatedAuditLogs } from '@/api/types'

export async function getAuditLogs(page: number, pageSize: number): Promise<PaginatedAuditLogs> {
  const { data } = await client.get<PaginatedAuditLogs>('/audit-logs', {
    params: { page, page_size: pageSize },
  })
  return data
}
