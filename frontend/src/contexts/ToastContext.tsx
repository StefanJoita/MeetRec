import { createContext, useContext, useState, useCallback, ReactNode } from 'react'
import { CheckCircle2, AlertCircle, Info, X } from 'lucide-react'
import { cn } from '@/lib/cn'

type ToastType = 'success' | 'error' | 'info'

interface Toast {
  id: number
  type: ToastType
  message: string
}

interface ToastContextType {
  toast: (message: string, type?: ToastType) => void
}

const ToastContext = createContext<ToastContextType | null>(null)

let nextId = 1

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const toast = useCallback((message: string, type: ToastType = 'info') => {
    const id = nextId++
    setToasts(prev => [...prev, { id, type, message }])
    const timerId = setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id))
    }, 4500)
    return () => clearTimeout(timerId)
  }, [])

  function dismiss(id: number) {
    setToasts(prev => prev.filter(t => t.id !== id))
  }

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div
        aria-live="polite"
        aria-atomic="false"
        className="fixed bottom-5 right-5 z-50 flex flex-col gap-2.5 max-w-sm w-full pointer-events-none"
      >
        {toasts.map(t => (
          <ToastItem key={t.id} toast={t} onDismiss={() => dismiss(t.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  )
}

function ToastItem({ toast: t, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  const config: Record<ToastType, { bar: string; icon: React.ReactNode }> = {
    success: {
      bar:  'bg-emerald-500',
      icon: <CheckCircle2 className="h-4.5 w-4.5 text-emerald-500 shrink-0" />,
    },
    error: {
      bar:  'bg-rose-500',
      icon: <AlertCircle className="h-4.5 w-4.5 text-rose-500 shrink-0" />,
    },
    info: {
      bar:  'bg-primary-500',
      icon: <Info className="h-4.5 w-4.5 text-primary-500 shrink-0" />,
    },
  }

  const { bar, icon } = config[t.type]

  return (
    <div
      role="status"
      className={cn(
        'pointer-events-auto relative overflow-hidden',
        'flex items-start gap-3 rounded-xl px-4 py-3.5 text-sm text-slate-800',
        'bg-white shadow-lg shadow-slate-900/10 ring-1 ring-slate-900/5',
        'animate-slide-in-right'
      )}
    >
      {/* Color accent bar */}
      <div className={cn('absolute left-0 top-0 bottom-0 w-1 rounded-l-xl', bar)} />

      <div className="pl-1 flex items-start gap-3 flex-1">
        {icon}
        <p className="flex-1 leading-snug pt-px">{t.message}</p>
        <button
          onClick={onDismiss}
          aria-label="Închide notificarea"
          className="shrink-0 text-slate-400 hover:text-slate-600 transition-colors ml-1"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  )
}

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast trebuie folosit în interiorul ToastProvider')
  return ctx.toast
}
