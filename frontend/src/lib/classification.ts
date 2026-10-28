// Nivelurile de clasificare ale unei înregistrări, în ordinea crescătoare a sensibilității.
// Aceeași listă ca în API (services/api/src/services/classification.py).

export type ClassificationCode = 'N' | 'SSv' | 'S' | 'SS'

export interface ClassificationLevel {
  code: ClassificationCode
  label: string
  /** Culorile etichetei (inactiv) și ale opțiunii alese în formular. */
  badge: string
  selected: string
}

export const CLASSIFICATIONS: ClassificationLevel[] = [
  { code: 'N',   label: 'Neclasificat',
    badge: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20', selected: 'border-emerald-500 bg-emerald-50 text-emerald-800 ring-emerald-500' },
  { code: 'SSv', label: 'Secret de serviciu',
    badge: 'bg-sky-50 text-sky-700 ring-sky-600/20',             selected: 'border-sky-500 bg-sky-50 text-sky-800 ring-sky-500' },
  { code: 'S',   label: 'Secret',
    badge: 'bg-amber-50 text-amber-800 ring-amber-600/25',       selected: 'border-amber-500 bg-amber-50 text-amber-900 ring-amber-500' },
  { code: 'SS',  label: 'Strict secret',
    badge: 'bg-rose-50 text-rose-700 ring-rose-600/20',          selected: 'border-rose-500 bg-rose-50 text-rose-800 ring-rose-500' },
]

export function classificationLevel(code: string): ClassificationLevel {
  return CLASSIFICATIONS.find(c => c.code === code) ?? CLASSIFICATIONS[0]
}
