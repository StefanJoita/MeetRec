import { createContext, useContext, useState, useCallback, ReactNode } from 'react'
import { CheckCircle, AlertCircle, Info, X } from 'lucide-react'
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
      {/* Toast container — bottom-right */}
      <div
        aria-live="polite"
        aria-atomic="false"
        className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm w-full pointer-events-none"
      >
        {toasts.map(t => (
          <ToastItem key={t.id} toast={t} onDismiss={() => dismiss(t.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  )
}

function ToastItem({ toast: t, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  const styles: Record<ToastType, { wrapper: string; icon: React.ReactNode }> = {
    success: {
      wrapper: 'bg-white border border-green-200 shadow-lg',
      icon: <CheckCircle className="h-5 w-5 text-green-500 shrink-0" />,
    },
    error: {
      wrapper: 'bg-white border border-red-200 shadow-lg',
      icon: <AlertCircle className="h-5 w-5 text-red-500 shrink-0" />,
    },
    info: {
      wrapper: 'bg-white border border-blue-200 shadow-lg',
      icon: <Info className="h-5 w-5 text-blue-500 shrink-0" />,
    },
  }

  const { wrapper, icon } = styles[t.type]

  return (
    <div
      role="status"
      className={cn(
        'pointer-events-auto flex items-start gap-3 rounded-xl px-4 py-3 text-sm text-gray-800',
        'animate-in slide-in-from-right-4 fade-in duration-200',
        wrapper
      )}
    >
      {icon}
      <p className="flex-1 leading-snug">{t.message}</p>
      <button
        onClick={onDismiss}
        aria-label="Închide notificarea"
        className="shrink-0 text-gray-400 hover:text-gray-600 transition-colors"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  )
}

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast trebuie folosit în interiorul ToastProvider')
  return ctx.toast
}
