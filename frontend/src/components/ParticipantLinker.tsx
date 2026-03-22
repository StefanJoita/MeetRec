import { useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { UserPlus, X, Search, Loader2 } from 'lucide-react'
import { useParticipantSuggest } from '@/hooks/useParticipantSuggest'
import { addRecordingParticipant, removeRecordingParticipant } from '@/api/recordings'
import { useToast } from '@/contexts/ToastContext'
import type { ParticipantUserInfo, UserSuggest } from '@/api/types'

const ROLE_LABEL: Record<string, string> = {
  admin: 'Admin',
  operator: 'Operator',
  participant: 'Participant',
}

const ROLE_COLOR: Record<string, string> = {
  admin: 'bg-blue-100 text-blue-700',
  operator: 'bg-gray-100 text-gray-600',
  participant: 'bg-green-100 text-green-700',
}

interface Props {
  recordingId: string
  linked: ParticipantUserInfo[]
}

/**
 * Componentă pentru linkarea participanților la o înregistrare.
 * Funcționează ca Outlook Ctrl+K: tastezi un nume/email, apar sugestii,
 * selectezi utilizatorul și îl adaugi.
 * Admin-only.
 */
export default function ParticipantLinker({ recordingId, linked }: Props) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)

  const [query, setQuery] = useState('')
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const { suggestions, loading: suggestLoading } = useParticipantSuggest(query)

  // Filtrăm sugestiile — excludem utilizatorii deja linkați
  const linkedIds = new Set(linked.map(p => p.user_id))
  const filtered = suggestions.filter(s => !linkedIds.has(s.id))

  const addMutation = useMutation({
    mutationFn: (userId: string) => addRecordingParticipant(recordingId, userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['recording', recordingId] })
      queryClient.invalidateQueries({ queryKey: ['recording-participants', recordingId] })
      toast('Participant adăugat.', 'success')
      setQuery('')
      setDropdownOpen(false)
    },
    onError: (err: any) => {
      toast(err?.response?.data?.detail ?? 'Nu am putut adăuga participantul.', 'error')
    },
  })

  const removeMutation = useMutation({
    mutationFn: (userId: string) => removeRecordingParticipant(recordingId, userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['recording', recordingId] })
      queryClient.invalidateQueries({ queryKey: ['recording-participants', recordingId] })
      toast('Participant eliminat.', 'success')
    },
    onError: (err: any) => {
      toast(err?.response?.data?.detail ?? 'Nu am putut elimina participantul.', 'error')
    },
  })

  function handleSelect(user: UserSuggest) {
    if (user.role !== 'participant') {
      toast('Doar utilizatorii cu rol "Participant" pot fi asociați unei înregistrări.', 'error')
      return
    }
    addMutation.mutate(user.id)
  }

  return (
    <div>
      {/* Participanți linkați */}
      {linked.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-3">
          {linked.map(p => (
            <div
              key={p.user_id}
              className="inline-flex items-center gap-2 bg-green-50 border border-green-200 rounded-lg px-3 py-1.5"
            >
              <div className="w-6 h-6 rounded-full bg-green-200 flex items-center justify-center text-xs font-semibold text-green-800 shrink-0">
                {(p.full_name ?? p.username).charAt(0).toUpperCase()}
              </div>
              <div className="min-w-0">
                <div className="text-sm font-medium text-gray-800 truncate max-w-[140px]">
                  {p.full_name ?? p.username}
                </div>
                <div className="text-xs text-gray-400 truncate max-w-[140px]">{p.email}</div>
              </div>
              <button
                onClick={() => removeMutation.mutate(p.user_id)}
                disabled={removeMutation.isPending}
                className="text-gray-400 hover:text-red-500 transition-colors ml-1"
                aria-label={`Elimină ${p.full_name ?? p.username}`}
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Input autocomplete */}
      <div className="relative">
        <div className="flex items-center gap-2 px-3 py-2 border border-gray-300 rounded-lg focus-within:ring-2 focus-within:ring-blue-500 focus-within:border-blue-500 bg-white">
          {suggestLoading
            ? <Loader2 className="h-4 w-4 text-gray-400 shrink-0 animate-spin" />
            : <Search className="h-4 w-4 text-gray-400 shrink-0" />
          }
          <input
            ref={inputRef}
            value={query}
            onChange={e => {
              setQuery(e.target.value)
              setDropdownOpen(true)
            }}
            onFocus={() => setDropdownOpen(true)}
            onBlur={() => setTimeout(() => setDropdownOpen(false), 150)}
            placeholder="Caută participant după nume sau email..."
            className="flex-1 text-sm outline-none bg-transparent placeholder-gray-400"
            aria-label="Caută utilizator participant"
            aria-autocomplete="list"
            aria-expanded={dropdownOpen && filtered.length > 0}
          />
          {query && (
            <button
              onClick={() => { setQuery(''); inputRef.current?.focus() }}
              className="text-gray-400 hover:text-gray-600"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        {/* Dropdown sugestii */}
        {dropdownOpen && query.trim().length > 0 && (
          <div
            className="absolute top-full left-0 right-0 mt-1 bg-white border border-gray-200 rounded-xl shadow-lg z-20 overflow-hidden"
            role="listbox"
          >
            {filtered.length === 0 && !suggestLoading && (
              <div className="px-4 py-3 text-sm text-gray-400 text-center">
                {suggestions.length > 0
                  ? 'Toți utilizatorii găsiți sunt deja asociați.'
                  : 'Niciun utilizator găsit.'}
              </div>
            )}
            {filtered.map(user => (
              <button
                key={user.id}
                role="option"
                onMouseDown={() => handleSelect(user)}
                className={`w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-gray-50 transition-colors ${user.role !== 'participant' ? 'opacity-50 cursor-not-allowed' : ''}`}
                disabled={user.role !== 'participant'}
                title={user.role !== 'participant' ? 'Doar participanții pot fi asociați' : undefined}
              >
                <div className="w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center text-sm font-semibold text-blue-700 shrink-0">
                  {(user.full_name ?? user.username).charAt(0).toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-gray-800 truncate">
                      {user.full_name ?? user.username}
                    </span>
                    <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${ROLE_COLOR[user.role] ?? 'bg-gray-100 text-gray-600'}`}>
                      {ROLE_LABEL[user.role] ?? user.role}
                    </span>
                  </div>
                  <div className="text-xs text-gray-400 truncate">{user.email}</div>
                </div>
                {user.role === 'participant' && (
                  <UserPlus className="h-4 w-4 text-gray-400 shrink-0" />
                )}
              </button>
            ))}
          </div>
        )}
      </div>

      {linked.length === 0 && (
        <p className="text-xs text-gray-400 mt-2">
          Niciun participant asociat. Caută mai sus pentru a acorda acces unui utilizator cu rol Participant.
        </p>
      )}
    </div>
  )
}
