import { CLASSIFICATIONS, type ClassificationCode } from '@/lib/classification'

interface Props {
  value: ClassificationCode | ''
  onChange: (value: ClassificationCode) => void
  disabled?: boolean
  /** Evidențiază câmpul cât timp nu e ales niciun nivel. */
  showRequired?: boolean
  id?: string
}

/** Nivelul de clasificare al înregistrării: obligatoriu, fără valoare preselectată. */
export default function ClassificationPicker({ value, onChange, disabled, showRequired, id = 'classification' }: Props) {
  const missing = showRequired && !value
  return (
    <div>
      <label htmlFor={id} className="block text-xs font-medium text-gray-600 mb-1">
        Nivel de clasificare <span className="text-rose-600" aria-hidden>*</span>
      </label>
      <select
        id={id}
        required
        value={value}
        disabled={disabled}
        onChange={e => onChange(e.target.value as ClassificationCode)}
        aria-invalid={missing || undefined}
        className={`input-base w-full ${value ? '' : 'text-gray-400'} ${missing ? 'border-amber-400' : ''}`}
      >
        <option value="" disabled>Alegeți nivelul de clasificare…</option>
        {CLASSIFICATIONS.map(level => (
          <option key={level.code} value={level.code} className="text-gray-900">
            {level.label} ({level.code})
          </option>
        ))}
      </select>
    </div>
  )
}
