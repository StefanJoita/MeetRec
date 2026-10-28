import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RotateCcw, Save } from 'lucide-react'
import { getSettings, resetSetting, updateSetting, type AppSetting, type SettingValue } from '@/api/admin'
import { CLASSIFICATION_QUERY_KEY } from '@/components/layout/ClassificationBanner'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { SkeletonTable } from '@/components/ui/Skeleton'
import { useToast } from '@/contexts/ToastContext'

const GROUP_ORDER = ['Securitate', 'Transcriere', 'Joburi', 'Încărcare', 'Retenție']

// Scăderea acestor valori poate șterge date la următoarea rulare a retenției
const DESTRUCTIVE_ON_DECREASE = new Set(['retention_days', 'audit_log_retention_days'])

function formatValue(s: AppSetting, value: SettingValue): string {
  if (s.type === 'bool') return value ? 'Activat' : 'Dezactivat'
  if (s.type === 'text') return String(value)
  if (value === null) return 'automat'
  return s.unit ? `${value} ${s.unit}` : String(value)
}

function errorDetail(error: unknown, fallback: string): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof detail === 'string' ? detail : fallback
}

export default function SettingsPanel() {
  const toast = useToast()
  const queryClient = useQueryClient()
  // valorile editate și nesalvate, pe cheie (text pentru câmpurile numerice)
  const [drafts, setDrafts] = useState<Record<string, string | boolean>>({})
  const [pendingConfirm, setPendingConfirm] = useState<{ setting: AppSetting; value: SettingValue } | null>(null)

  const { data: settings, isLoading, isError } = useQuery<AppSetting[]>({
    queryKey: ['admin-settings'],
    queryFn: getSettings,
    retry: false,
  })

  function onSaved(updated: AppSetting[], key: string, message: string) {
    queryClient.setQueryData(['admin-settings'], updated)
    queryClient.invalidateQueries({ queryKey: ['admin-system'] })
    queryClient.invalidateQueries({ queryKey: CLASSIFICATION_QUERY_KEY })
    setDrafts(d => {
      const next = { ...d }
      delete next[key]
      return next
    })
    toast(message, 'success')
  }

  const saveMutation = useMutation({
    mutationFn: ({ key, value }: { key: string; value: SettingValue }) => updateSetting(key, value),
    onSuccess: (updated, { key }) => onSaved(updated, key, 'Setare salvată.'),
    onError: error => toast(errorDetail(error, 'Nu am putut salva setarea.'), 'error'),
  })

  const resetMutation = useMutation({
    mutationFn: (key: string) => resetSetting(key),
    onSuccess: (updated, key) => onSaved(updated, key, 'Setarea a revenit la valoarea din configurare.'),
    onError: error => toast(errorDetail(error, 'Nu am putut reseta setarea.'), 'error'),
  })

  function draftValue(s: AppSetting): string | boolean {
    if (s.key in drafts) return drafts[s.key]
    if (s.type === 'bool') return Boolean(s.value)
    return s.value === null ? '' : String(s.value)
  }

  function parsed(s: AppSetting): { value: SettingValue; error?: string } {
    const raw = draftValue(s)
    if (s.type === 'bool') return { value: raw as boolean }
    if (s.type === 'text') {
      const value = String(raw).replace(/\s+/g, ' ').trim()
      if (value === '') return { value, error: 'Valoare obligatorie.' }
      if (s.max !== null && value.length > s.max) return { value, error: `Maxim ${s.max} de caractere.` }
      return { value }
    }
    const text = String(raw).trim()
    if (text === '') {
      return s.type === 'optional_int' ? { value: null } : { value: null, error: 'Valoare obligatorie.' }
    }
    if (!/^\d+$/.test(text)) return { value: null, error: 'Număr întreg.' }
    const n = Number(text)
    if (s.min !== null && n < s.min) return { value: n, error: `Minim ${s.min}.` }
    if (s.max !== null && n > s.max) return { value: n, error: `Maxim ${s.max}.` }
    return { value: n }
  }

  function save(s: AppSetting) {
    const { value, error } = parsed(s)
    if (error) return
    const lowered = typeof value === 'number' && typeof s.value === 'number' && value < s.value
    if (DESTRUCTIVE_ON_DECREASE.has(s.key) && lowered) {
      setPendingConfirm({ setting: s, value })
      return
    }
    saveMutation.mutate({ key: s.key, value })
  }

  if (isLoading) return <SkeletonTable rows={8} cols={3} />
  if (isError || !settings) {
    return <div className="card-padded text-sm text-red-600">Nu am putut încărca setările.</div>
  }

  const groups = GROUP_ORDER.map(g => ({ name: g, items: settings.filter(s => s.group === g) }))
    .filter(g => g.items.length > 0)

  return (
    <div className="space-y-6">
      {groups.map(group => (
        <section key={group.name} className="card divide-y divide-gray-100">
          <h2 className="px-5 py-3 text-sm font-semibold text-gray-700">{group.name}</h2>
          {group.items.map(s => {
            const current = draftValue(s)
            const { value, error } = parsed(s)
            const dirty = s.key in drafts && value !== s.value
            const busy = saveMutation.isPending || resetMutation.isPending
            return (
              <div key={s.key} className="px-5 py-4 flex flex-col md:flex-row md:items-start gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <label htmlFor={`setting-${s.key}`} className="text-sm font-medium text-gray-900">
                      {s.label}
                    </label>
                    {s.source === 'interfata' ? (
                      <span className="text-[11px] px-2 py-0.5 rounded-full bg-blue-50 text-blue-700"
                            title={s.updated_by ? `Modificat de ${s.updated_by}` : undefined}>
                        Setat din interfață · implicit {formatValue(s, s.env_value)}
                      </span>
                    ) : (
                      <span className="text-[11px] px-2 py-0.5 rounded-full bg-gray-100 text-gray-500">
                        Din configurare (.env)
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-500 mt-1">{s.description}</p>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  {s.type === 'bool' ? (
                    <button
                      id={`setting-${s.key}`}
                      type="button"
                      role="switch"
                      aria-checked={current as boolean}
                      disabled={busy}
                      onClick={() => setDrafts(d => ({ ...d, [s.key]: !(current as boolean) }))}
                      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                        current ? 'bg-blue-600' : 'bg-gray-300'
                      }`}
                    >
                      <span className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform ${
                        current ? 'translate-x-5' : 'translate-x-0.5'
                      }`} />
                    </button>
                  ) : s.type === 'text' ? (
                    <div className="flex flex-col">
                      <input
                        id={`setting-${s.key}`}
                        value={current as string}
                        maxLength={s.max ?? undefined}
                        disabled={busy}
                        onChange={e => setDrafts(d => ({ ...d, [s.key]: e.target.value }))}
                        onKeyDown={e => { if (e.key === 'Enter') save(s) }}
                        className={`w-full md:w-72 text-sm border rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                          error ? 'border-red-400' : 'border-gray-300'
                        }`}
                      />
                      {error && <span className="text-[11px] text-red-600 mt-1">{error}</span>}
                    </div>
                  ) : (
                    <div className="flex flex-col">
                      <div className="flex items-center gap-1.5">
                        <input
                          id={`setting-${s.key}`}
                          inputMode="numeric"
                          value={current as string}
                          placeholder={s.type === 'optional_int' ? 'automat' : undefined}
                          disabled={busy}
                          onChange={e => setDrafts(d => ({ ...d, [s.key]: e.target.value }))}
                          onKeyDown={e => { if (e.key === 'Enter') save(s) }}
                          className={`w-24 text-sm border rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                            error ? 'border-red-400' : 'border-gray-300'
                          }`}
                        />
                        {s.unit && <span className="text-xs text-gray-500">{s.unit}</span>}
                      </div>
                      {error && <span className="text-[11px] text-red-600 mt-1">{error}</span>}
                    </div>
                  )}

                  <button
                    type="button"
                    onClick={() => save(s)}
                    disabled={!dirty || !!error || busy}
                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-blue-600 text-white disabled:opacity-40"
                  >
                    <Save className="h-3.5 w-3.5" /> Salvează
                  </button>
                  {s.source === 'interfata' && (
                    <button
                      type="button"
                      onClick={() => resetMutation.mutate(s.key)}
                      disabled={busy}
                      title={`Revino la ${formatValue(s, s.env_value)} (din .env)`}
                      className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium border border-gray-300 text-gray-600 hover:bg-gray-50"
                    >
                      <RotateCcw className="h-3.5 w-3.5" /> Implicit
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </section>
      ))}

      <ConfirmDialog
        open={pendingConfirm !== null}
        danger
        title="Reduceți perioada de păstrare?"
        description={pendingConfirm
          ? `La următoarea rulare a politicii de retenție vor fi șterse definitiv datele mai vechi de ${pendingConfirm.value} zile (${pendingConfirm.setting.label.toLowerCase()}). Operația nu poate fi anulată.`
          : ''}
        confirmLabel="Reduce perioada"
        onConfirm={() => {
          if (pendingConfirm) saveMutation.mutate({ key: pendingConfirm.setting.key, value: pendingConfirm.value })
          setPendingConfirm(null)
        }}
        onClose={() => setPendingConfirm(null)}
      />
    </div>
  )
}
