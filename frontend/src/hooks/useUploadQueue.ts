import { useCallback, useRef, useState } from 'react'
import client from '@/api/client'

// Coada paginii „Încarcă fișiere”: fișierele pleacă pe rând, fiecare cu progresul
// și rezultatul lui. Un fișier respins (prea mare, format, duplicat) nu oprește coada.

export type UploadItemStatus = 'pending' | 'uploading' | 'done' | 'error'

export interface UploadItem {
  id: number
  file: File
  status: UploadItemStatus
  progress: number               // 0–100
  error: string
  duplicateOf: string | null     // id-ul înregistrării existente, la fișier deja încărcat (409)
}

export interface UploadMetadata {
  title?: string
  meeting_date?: string
  description?: string
  participants?: string
  location?: string
}

let nextId = 1

/** Mesajul serverului: text, sau { message, recording_id } la fișier duplicat (409). */
function uploadError(e: unknown): { message: string; duplicateOf: string | null } {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string') return { message: detail, duplicateOf: null }
  if (typeof detail === 'object' && detail !== null) {
    const d = detail as { message?: string; recording_id?: string }
    return { message: d.message ?? 'Fișierul a fost respins.', duplicateOf: d.recording_id ?? null }
  }
  return { message: 'Nu am putut încărca fișierul. Verificați conexiunea și încercați din nou.', duplicateOf: null }
}

export function useUploadQueue() {
  const [items, setItems] = useState<UploadItem[]>([])
  const [running, setRunning] = useState(false)
  const itemsRef = useRef(items)
  itemsRef.current = items
  const abortRef = useRef<AbortController | null>(null)
  const cancelledRef = useRef(false)

  const update = useCallback((id: number, patch: Partial<UploadItem>) => {
    setItems(list => list.map(it => (it.id === id ? { ...it, ...patch } : it)))
  }, [])

  /** Adaugă fișiere; `check` întoarce motivul respingerii locale (mărime, format) sau ''. */
  const add = useCallback((files: File[], check: (f: File) => string) => {
    setItems(list => {
      const known = new Set(list.map(it => `${it.file.name}|${it.file.size}`))
      const fresh = files
        .filter(f => !known.has(`${f.name}|${f.size}`))
        .map((file): UploadItem => {
          const error = check(file)
          return { id: nextId++, file, status: error ? 'error' : 'pending', progress: 0, error, duplicateOf: null }
        })
      return [...list, ...fresh]
    })
  }, [])

  const remove = useCallback((id: number) => setItems(list => list.filter(it => it.id !== id)), [])
  const clear = useCallback(() => setItems([]), [])

  /** Trimite pe rând fișierele în așteptare. `metaFor` dă metadatele fiecăruia. */
  const start = useCallback(async (metaFor: (item: UploadItem) => UploadMetadata) => {
    cancelledRef.current = false
    setRunning(true)
    // Lista de la apăsarea butonului: fișierele adăugate între timp așteaptă următorul „Trimite”
    for (const item of itemsRef.current.filter(it => it.status === 'pending')) {
      if (cancelledRef.current) break
      const controller = new AbortController()
      abortRef.current = controller
      update(item.id, { status: 'uploading', progress: 0, error: '' })

      const meta = metaFor(item)
      const form = new FormData()
      form.append('file', item.file)
      for (const [key, value] of Object.entries(meta)) if (value) form.append(key, value)

      try {
        await client.post('/inbox/upload', form, {
          headers: { 'Content-Type': 'multipart/form-data' },
          signal: controller.signal,
          onUploadProgress(event) {
            update(item.id, { progress: event.total ? Math.round((event.loaded / event.total) * 100) : 0 })
          },
        })
        update(item.id, { status: 'done', progress: 100 })
      } catch (e) {
        if ((e as { name?: string })?.name === 'CanceledError') {
          update(item.id, { status: 'pending', progress: 0 })
          break
        }
        const { message, duplicateOf } = uploadError(e)
        update(item.id, { status: 'error', error: message, duplicateOf })
      }
    }
    abortRef.current = null
    setRunning(false)
  }, [update])

  /** Oprește fișierul în curs; el și cele rămase revin „în așteptare”. */
  const cancel = useCallback(() => {
    cancelledRef.current = true
    abortRef.current?.abort()
  }, [])

  return { items, running, add, remove, clear, start, cancel }
}
