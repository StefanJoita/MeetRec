import client from '@/api/client'
import type { PaginatedAuditLogs } from '@/api/types'

export type AuditResourceGroup = 'recording' | 'user' | 'app_setting' | 'audit_logs'

export interface AuditLogFilters {
  search?: string
  action?: string
  resource?: AuditResourceGroup | ''
}

function filterParams({ search, action, resource }: AuditLogFilters): Record<string, string> {
  return {
    ...(search ? { search } : {}),
    ...(action ? { action } : {}),
    ...(resource ? { resource } : {}),
  }
}

export async function getAuditLogs(page: number, pageSize: number, filters: AuditLogFilters = {}): Promise<PaginatedAuditLogs> {
  const { data } = await client.get<PaginatedAuditLogs>('/audit-logs', {
    params: { page, page_size: pageSize, ...filterParams(filters) },
  })
  return data
}

export function downloadAuditLogsCsv(filters: AuditLogFilters = {}): void {
  const params = new URLSearchParams(filterParams(filters))
  const token = localStorage.getItem('access_token')
  const base  = '/api/v1'
  const url   = `${base}/audit-logs/export${params.size ? '?' + params.toString() : ''}`

  // Fetch cu token și trigger download manual
  fetch(url, { headers: { Authorization: `Bearer ${token}` } })
    .then(async res => {
      // Numele vine de la server (AAAALLZZ_Jurnal_audit.csv)
      const match = res.headers.get('Content-Disposition')?.match(/filename\*?=(?:UTF-8'')?([^;\n]+)/i)
      return { blob: await res.blob(), name: match ? decodeURIComponent(match[1].replace(/['"]/g, '')) : 'Jurnal_audit.csv' }
    })
    .then(({ blob, name }) => {
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = name
      a.click()
      URL.revokeObjectURL(a.href)
    })
}
