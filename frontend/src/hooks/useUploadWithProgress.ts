import { useState, useRef } from 'react'
import client from '@/api/client'
import type { InboxUploadResponse } from '@/api/recordings'

export interface UploadState {
  progress: number       // 0–100
  uploading: boolean
  done: boolean
  error: string
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
  })
  const abortRef = useRef<AbortController | null>(null)

  async function upload(file: File, meta?: UploadMetadata): Promise<InboxUploadResponse | null> {
    const controller = new AbortController()
    abortRef.current = controller

    setState({ progress: 0, uploading: true, done: false, error: '' })

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
      setState({ progress: 100, uploading: false, done: true, error: '' })
      return data
    } catch (e: unknown) {
      if ((e as { name?: string })?.name === 'CanceledError') {
        setState({ progress: 0, uploading: false, done: false, error: '' })
        return null
      }
      const msg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        ?? 'Nu am putut încărca fișierul. Încearcă din nou.'
      setState(s => ({ ...s, uploading: false, error: msg }))
      return null
    }
  }

  function cancel() {
    abortRef.current?.abort()
  }

  function reset() {
    setState({ progress: 0, uploading: false, done: false, error: '' })
  }

  return { ...state, upload, cancel, reset }
}
