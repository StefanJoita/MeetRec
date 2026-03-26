import { useEffect, useRef } from 'react'
import { AlertTriangle } from 'lucide-react'

interface ConfirmDialogProps {
  open: boolean
  title: string
  description: string
  confirmLabel?: string
  cancelLabel?: string
  danger?: boolean
  onConfirm: () => void
  onClose: () => void
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = 'Confirmă',
  cancelLabel = 'Anulează',
  danger = false,
  onConfirm,
  onClose,
}: ConfirmDialogProps) {
  const cancelRef = useRef<HTMLButtonElement>(null)

  // Focus pe "Anulează" la deschidere (pattern de siguranță)
  useEffect(() => {
    if (!open) return
    const timerId = setTimeout(() => cancelRef.current?.focus(), 50)
    return () => clearTimeout(timerId)
  }, [open])

  // Închide la Escape
  useEffect(() => {
    if (!open) return
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-dialog-title"
      aria-describedby="confirm-dialog-desc"
    >
      {/* Overlay */}
      <div
        className="absolute inset-0 bg-black/40 animate-fade-in"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Modal */}
      <div className="relative bg-white rounded-2xl shadow-xl max-w-md w-full p-6 animate-scale-in">
        {/* Iconiță */}
        <div className={`mx-auto mb-4 h-12 w-12 flex items-center justify-center rounded-full ${danger ? 'bg-red-100' : 'bg-yellow-100'}`}>
          <AlertTriangle className={`h-6 w-6 ${danger ? 'text-red-600' : 'text-yellow-600'}`} />
        </div>

        <h2
          id="confirm-dialog-title"
          className="text-lg font-semibold text-gray-900 text-center mb-2"
        >
          {title}
        </h2>
        <p
          id="confirm-dialog-desc"
          className="text-sm text-gray-500 text-center mb-6 leading-relaxed"
        >
          {description}
        </p>

        <div className="flex gap-3">
          <button
            ref={cancelRef}
            onClick={onClose}
            className="btn-secondary flex-1 justify-center"
          >
            {cancelLabel}
          </button>
          <button
            onClick={() => { onConfirm(); onClose() }}
            className={`flex-1 justify-center inline-flex items-center gap-2 font-medium px-4 py-2.5 rounded-lg text-sm transition-colors ${
              danger
                ? 'bg-red-600 hover:bg-red-700 text-white'
                : 'bg-blue-600 hover:bg-blue-700 text-white'
            }`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
