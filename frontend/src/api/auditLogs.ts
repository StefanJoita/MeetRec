import client from '@/api/client'
import type { PaginatedAuditLogs } from '@/api/types'

export async function getAuditLogs(page: number, pageSize: number, search?: string, action?: string): Promise<PaginatedAuditLogs> {
  const { data } = await client.get<PaginatedAuditLogs>('/audit-logs', {
    params: {
      page,
      page_size: pageSize,
      ...(search ? { search } : {}),
      ...(action ? { action } : {}),
    },
  })
  return data
}

export function downloadAuditLogsCsv(action?: string): void {
  const params = new URLSearchParams()
  if (action) params.set('action', action)
  const token = localStorage.getItem('access_token')
  const base  = '/api/v1'
  const url   = `${base}/audit-logs/export${params.size ? '?' + params.toString() : ''}`

  // Fetch cu token și trigger download manual
  fetch(url, { headers: { Authorization: `Bearer ${token}` } })
    .then(res => res.blob())
    .then(blob => {
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `audit-log-${new Date().toISOString().slice(0, 10)}.csv`
      a.click()
      URL.revokeObjectURL(a.href)
    })
}
