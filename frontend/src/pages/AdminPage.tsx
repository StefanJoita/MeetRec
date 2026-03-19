import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ShieldCheck, ChevronLeft, ChevronRight } from 'lucide-react'
import client from '@/api/client'
import { Spinner } from '@/components/ui/Spinner'
import type { PaginatedAuditLogs, AuditLog } from '@/api/types'

async function getAuditLogs(page: number, pageSize: number): Promise<PaginatedAuditLogs> {
  const { data } = await client.get<PaginatedAuditLogs>('/audit-logs', {
    params: { page, page_size: pageSize },
  })
  return data
}

const ACTION_COLORS: Record<string, string> = {
  UPLOAD: 'bg-blue-100 text-blue-700',
  VIEW: 'bg-gray-100 text-gray-600',
  SEARCH: 'bg-purple-100 text-purple-700',
  EXPORT: 'bg-green-100 text-green-700',
  DELETE: 'bg-red-100 text-red-700',
  TRANSCRIBE: 'bg-orange-100 text-orange-700',
  LOGIN: 'bg-indigo-100 text-indigo-700',
  RETENTION_DELETE: 'bg-red-100 text-red-700',
}

export default function AdminPage() {
  const [page, setPage] = useState(1)
  const pageSize = 20

  const { data, isLoading, isError } = useQuery({
    queryKey: ['audit-logs', page],
    queryFn: () => getAuditLogs(page, pageSize),
    retry: false,
  })

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex items-center gap-3 mb-6">
        <div className="h-9 w-9 bg-blue-50 rounded-lg flex items-center justify-center">
          <ShieldCheck className="h-5 w-5 text-blue-600" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Administrare</h1>
          <p className="text-sm text-gray-500">Log de audit — toate acțiunile utilizatorilor</p>
        </div>
      </div>

      {isLoading && (
        <div className="flex justify-center py-20"><Spinner className="h-8 w-8" /></div>
      )}

      {isError && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-center text-red-600 text-sm">
          Eroare la încărcarea logurilor. Verificați că aveți drepturi de administrator.
        </div>
      )}

      {data && (
        <>
          <div className="bg-white border border-gray-200 rounded-xl overflow-hidden mb-4">
            <table className="min-w-full divide-y divide-gray-100">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Timp</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Acțiune</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider hidden md:table-cell">Resursă</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider hidden lg:table-cell">IP</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {data.items.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-12 text-center text-gray-400 text-sm">
                      Nicio intrare în log.
                    </td>
                  </tr>
                )}
                {data.items.map((log: AuditLog) => (
                  <tr key={log.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap">
                      {new Date(log.timestamp).toLocaleString('ro-RO')}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${ACTION_COLORS[log.action] ?? 'bg-gray-100 text-gray-600'}`}>
                        {log.action}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500 hidden md:table-cell">
                      {log.resource_type ?? '—'}
                      {log.resource_id && (
                        <span className="ml-1 text-gray-300">({log.resource_id.slice(0, 8)}…)</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-400 font-mono hidden lg:table-cell">
                      {log.user_ip}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${log.success ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                        {log.success ? 'OK' : 'EȘUAT'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {data.pages > 1 && (
            <div className="flex items-center justify-between">
              <p className="text-sm text-gray-500">Pagina {data.page} din {data.pages} · {data.total} intrări</p>
              <div className="flex gap-2">
                <button
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="p-2 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-40"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <button
                  onClick={() => setPage(p => Math.min(data.pages, p + 1))}
                  disabled={page === data.pages}
                  className="p-2 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-40"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
