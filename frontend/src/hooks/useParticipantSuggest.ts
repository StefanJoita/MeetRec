import { useState, useEffect, useRef } from 'react'
import client from '@/api/client'
import type { UserSuggest } from '@/api/types'

/**
 * Hook pentru autocomplete utilizatori — stil Outlook Ctrl+K.
 * Trimite request la /users/suggest?q=<query> cu debounce 250ms.
 * Returnează sugestii pentru admin care vrea să linkeze un participant.
 */
export function useParticipantSuggest(query: string) {
  const [suggestions, setSuggestions] = useState<UserSuggest[]>([])
  const [loading, setLoading] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    const trimmed = query.trim()

    if (trimmed.length < 1) {
      setSuggestions([])
      return
    }

    const timer = setTimeout(async () => {
      // Anulăm request-ul precedent dacă există
      abortRef.current?.abort()
      abortRef.current = new AbortController()

      setLoading(true)
      try {
        const { data } = await client.get<UserSuggest[]>('/users/suggest', {
          params: { q: trimmed, role: 'participant' },
          signal: abortRef.current.signal,
        })
        setSuggestions(data)
      } catch {
        // Ignorăm abort errors (sunt așteptate la debounce)
        setSuggestions([])
      } finally {
        setLoading(false)
      }
    }, 250)

    return () => {
      clearTimeout(timer)
      abortRef.current?.abort()
    }
  }, [query])

  return { suggestions, loading }
}
