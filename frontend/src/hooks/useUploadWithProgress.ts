import { useState, useRef } from 'react'
import client from '@/api/client'
import type { InboxUploadResponse } from '@/api/recordings'

export interface UploadState {
  progress: number       // 0–100
  uploading: boolean
  done: boolean
  error: string
  duplicateOf: string | null   // id-ul înregistrării existente, la fișier deja încărcat (409)
}

export interface UploadMetadata {
  title?: string
  meeting_date?: string
  description?: string
  participants?: string
  location?: string
}

export function useUploadWithProgress() {
  const [state, setState] = useState<UploadState>({
    progress: 0,
    uploading: false,
    done: false,
    error: '',
    duplicateOf: null,
  })
  const abortRef = useRef<AbortController | null>(null)

  async function upload(file: File, meta?: UploadMetadata): Promise<InboxUploadResponse | null> {
    const controller = new AbortController()
    abortRef.current = controller

    setState({ progress: 0, uploading: true, done: false, error: '', duplicateOf: null })

    const form = new FormData()
    form.append('file', file)
    if (meta?.title) form.append('title', meta.title)
    if (meta?.meeting_date) form.append('meeting_date', meta.meeting_date)
    if (meta?.description) form.append('description', meta.description)
    if (meta?.participants) form.append('participants', meta.participants)
    if (meta?.location) form.append('location', meta.location)

    try {
      const { data } = await client.post<InboxUploadResponse>('/inbox/upload', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
        signal: controller.signal,
        onUploadProgress(event) {
          const pct = event.total
            ? Math.round((event.loaded / event.total) * 100)
            : 0
          setState(s => ({ ...s, progress: pct }))
        },
      })
      setState({ progress: 100, uploading: false, done: true, error: '', duplicateOf: null })
      return data
    } catch (e: unknown) {
      if ((e as { name?: string })?.name === 'CanceledError') {
        setState({ progress: 0, uploading: false, done: false, error: '', duplicateOf: null })
        return null
      }
      // detail: text, sau { message, recording_id } la fișier duplicat (409)
      const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
      const duplicate = typeof detail === 'object' && detail !== null
        ? detail as { message?: string; recording_id?: string }
        : null
      const msg = (typeof detail === 'string' ? detail : duplicate?.message)
        ?? 'Nu am putut încărca fișierul. Încearcă din nou.'
      setState(s => ({ ...s, uploading: false, error: msg, duplicateOf: duplicate?.recording_id ?? null }))
      return null
    }
  }

  function cancel() {
    abortRef.current?.abort()
  }

  function reset() {
    setState({ progress: 0, uploading: false, done: false, error: '', duplicateOf: null })
  }

  return { ...state, upload, cancel, reset }
}
