import { useQuery } from '@tanstack/react-query'
import { ShieldCheck } from 'lucide-react'
import { getClassification } from '@/api/admin'
import { cn } from '@/lib/cn'

export const CLASSIFICATION_QUERY_KEY = ['classification']

// Nivelul de secretizare, setat din Administrare → Setări. Apare pe fiecare pagină,
// inclusiv la autentificare. Până la răspunsul serverului banda rămâne goală,
// ca să nu afișeze un nivel greșit.
export function ClassificationBanner({ className }: { className?: string }) {
  const { data } = useQuery({
    queryKey: CLASSIFICATION_QUERY_KEY,
    queryFn: getClassification,
    staleTime: 60_000,
    refetchInterval: 60_000,
  })

  return (
    <div
      role="note"
      aria-label="Nivel de secretizare"
      className={cn(
        'shrink-0 h-7 flex items-center justify-center gap-2 px-4 bg-primary-50 border-b border-primary-100',
        className,
      )}
    >
      {data && (
        <>
          <ShieldCheck className="h-3.5 w-3.5 text-primary-500 shrink-0" aria-hidden />
          <span className="text-[11px] font-semibold tracking-[0.16em] text-primary-800 truncate">
            {data.level}
          </span>
        </>
      )}
    </div>
  )
}
