import { useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { getRecordingsActivity, type RecordingActivityItem } from '@/api/recordings'
import { useToast } from '@/contexts/ToastContext'

const POLL_MS = 20_000

/**
 * Anunță când se termină o transcriere, pe orice pagină: toast în aplicație și,
 * dacă fereastra nu e în față și utilizatorul a permis, notificare de sistem.
 * Se anunță doar înregistrările văzute în curs cât timp aplicația a fost deschisă
 * (aplicația nu reține cine a încărcat fiecare fișier).
 */
export function useTranscriptionNotifications() {
  const toast = useToast()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const location = useLocation()
  const pathRef = useRef(location.pathname)
  pathRef.current = location.pathname

  useEffect(() => {
    const watched = new Map<string, string>()       // id → titlu
    let since: string | null = null
    let stopped = false

    function notify(item: RecordingActivityItem) {
      const ok = item.status === 'completed'
      const cancelled = item.status === 'cancelled'
      const message = ok
        ? `Transcrierea „${item.title}” este gata.`
        : cancelled ? `Transcrierea „${item.title}” a fost anulată.` : `Transcrierea „${item.title}” a eșuat.`
      queryClient.invalidateQueries({ queryKey: ['recordings'] })
      queryClient.invalidateQueries({ queryKey: ['recording', item.id] })

      // Pe pagina înregistrării, pagina își afișează singură starea
      if (pathRef.current !== `/recordings/${item.id}`) toast(message, ok ? 'success' : cancelled ? 'info' : 'error')

      if (document.hidden && 'Notification' in window && Notification.permission === 'granted') {
        const n = new Notification('MeetRec', { body: message, tag: item.id })
        n.onclick = () => { window.focus(); navigate(`/recordings/${item.id}`); n.close() }
      }
    }

    async function poll() {
      try {
        const activity = await getRecordingsActivity(since)
        if (stopped) return
        since = activity.server_time
        activity.in_progress.forEach(r => watched.set(r.id, r.title))
        activity.finished.forEach(r => {
          if (watched.delete(r.id)) notify(r)
        })
      } catch {
        // rețea / sesiune: reîncercăm la următorul interval
      }
    }

    poll()
    const timer = setInterval(poll, POLL_MS)
    return () => { stopped = true; clearInterval(timer) }
  }, [toast, navigate, queryClient])
}

/** Cere permisiunea pentru notificări de sistem (apelat la o acțiune a utilizatorului). */
export function requestNotificationPermission() {
  if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission().catch(() => {})
  }
}
