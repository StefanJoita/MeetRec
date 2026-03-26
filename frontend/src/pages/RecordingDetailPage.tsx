import { useState, useRef, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient, type Query } from '@tanstack/react-query'
import axios from 'axios'
import {
  ArrowLeft, Download, RefreshCw, Trash2,
  Calendar, Clock, MapPin, Users, FileAudio, ChevronDown, Check, ChevronRight,
} from 'lucide-react'
import client from '@/api/client'
import { getRecording, retryTranscription, deleteRecording, getRecordingParticipants } from '@/api/recordings'
import { getTranscript } from '@/api/transcripts'
import type { ParticipantUserInfo, Recording, Segment, Transcript } from '@/api/types'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { Spinner } from '@/components/ui/Spinner'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { SkeletonCard } from '@/components/ui/Skeleton'
import { Tooltip } from '@/components/ui/Tooltip'
import { useToast } from '@/contexts/ToastContext'
import { useAuth } from '@/contexts/AuthContext'
import AudioPlayer, { type AudioPlayerHandle } from '@/components/AudioPlayer'
import TranscriptViewer from '@/components/TranscriptViewer'
import TranscriptionProgress from '@/components/recording/TranscriptionProgress'
import ParticipantLinker from '@/components/ParticipantLinker'

const EXPORT_FORMATS = [
  { value: 'txt', label: 'Text (.txt)' },
  { value: 'pdf', label: 'PDF (.pdf)' },
  { value: 'docx', label: 'Word (.docx)' },
]

export default function RecordingDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { user } = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const toast = useToast()
  const [currentTime, setCurrentTime] = useState(0)
  const audioPlayerRef = useRef<AudioPlayerHandle>(null)
  const [exportOpen, setExportOpen] = useState(false)
  const [showDeleteDialog, setShowDeleteDialog] = useState(false)
  const [copied, setCopied] = useState(false)
  const exportRef = useRef<HTMLDivElement>(null)
  const prevStatusRef = useRef<string | null>(null)

  // Închide dropdown export la click în afară
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (exportRef.current && !exportRef.current.contains(e.target as Node)) {
        setExportOpen(false)
      }
    }
    if (exportOpen) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [exportOpen])

  // Toast când transcrierea se finalizează
  const { data: recording, isLoading: recLoading } = useQuery<Recording>({
    queryKey: ['recording', id],
    queryFn: () => getRecording(id!),
    refetchInterval: (query: Query<Recording, Error, Recording, readonly unknown[]>) => {
      const status = query.state.data?.status
      return status === 'queued' || status === 'transcribing' ? 5000 : false
    },
    select: (data: Recording) => {
      // Notifică când transcrierea trece de la activ la completed
      if (
        prevStatusRef.current &&
        (prevStatusRef.current === 'queued' || prevStatusRef.current === 'transcribing') &&
        data.status === 'completed'
      ) {
        toast('Transcrierea s-a finalizat cu succes!', 'success')
      }
      if (
        prevStatusRef.current &&
        (prevStatusRef.current === 'queued' || prevStatusRef.current === 'transcribing') &&
        data.status === 'failed'
      ) {
        toast('Transcrierea nu a putut fi finalizată.', 'error')
      }
      prevStatusRef.current = data.status
      return data
    },
  })

  const { data: transcript, isLoading: txLoading } = useQuery<Transcript>({
    queryKey: ['transcript', id],
    queryFn: () => getTranscript(id!),
    enabled: recording?.status === 'completed',
    retry: false,
  })

  const canManageParticipants = !!user && user.role !== 'participant'

  const { data: resolvedParticipants } = useQuery<ParticipantUserInfo[]>({
    queryKey: ['recording-participants', id],
    queryFn: () => getRecordingParticipants(id!),
    enabled: !!id && canManageParticipants,
  })

  const retryMutation = useMutation({
    mutationFn: () => retryTranscription(id!),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['recording', id] }),
  })

  const deleteMutation = useMutation({
    mutationFn: () => deleteRecording(id!),
    onSuccess: () => navigate('/'),
    onError: (error: unknown) => {
      const message = axios.isAxiosError(error)
        ? (error.response?.data?.detail as string | undefined)
        : undefined
      toast(message ?? 'Înregistrarea nu a putut fi ștearsă.', 'error')
    },
  })

  function handleExport(format: string) {
    client
      .get(`/export/recording/${id}?format=${format}`, {
        responseType: 'blob',
      })
      .then((response) => {
        const blob = response.data
        const blobUrl = URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = blobUrl
        // Preia numele fișierului din header-ul Content-Disposition
        const disposition = response.headers['content-disposition'] as string | undefined
        const match = disposition?.match(/filename\*?=(?:UTF-8'')?([^;\n]+)/i)
        link.download = match ? decodeURIComponent(match[1].replace(/['"]/g, '')) : `recording-${id}.${format}`
        link.click()
        URL.revokeObjectURL(blobUrl)
        setExportOpen(false)
      })
      .catch((err) => {
        const status = axios.isAxiosError(err) ? err.response?.status : null
        if (status === 429) {
          toast('Limita de export a fost atinsă. Încearcă din nou mai târziu.', 'error')
        } else {
          toast('Exportul nu a putut fi generat. Încearcă din nou.', 'error')
        }
      })
  }

  if (recLoading) {
    return <SkeletonCard />
  }

  if (!recording) {
    return (
      <div className="p-6 text-center">
        <p className="text-gray-500">Înregistrarea nu a fost găsită.</p>
        <Link to="/" className="text-blue-600 text-sm mt-2 inline-block">Înapoi la listă</Link>
      </div>
    )
  }

  const isProcessing = recording.status === 'queued' || recording.status === 'transcribing'

  return (
    <div className="p-6 max-w-5xl mx-auto">
      {/* Breadcrumbs */}
      <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-sm mb-6">
        <button
          onClick={() => navigate(-1)}
          className="inline-flex items-center gap-1 text-slate-500 hover:text-primary-600 transition-colors"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Înregistrări
        </button>
        <ChevronRight className="h-3.5 w-3.5 text-slate-300 shrink-0" />
        <span
          className="text-slate-800 font-medium truncate max-w-xs"
          title={recording.title}
        >
          {recording.title}
        </span>
      </nav>

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4 mb-6">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2.5 mb-2">
            <StatusBadge status={recording.status} />
            <span className="text-xs text-slate-400 font-medium">{recording.audio_format.toUpperCase()}</span>
          </div>
          <h1 className="text-2xl font-bold text-slate-900 leading-tight tracking-tight">{recording.title}</h1>
          {recording.description && (
            <p className="text-slate-500 text-sm mt-1.5">{recording.description}</p>
          )}
        </div>

        {/* Acțiuni */}
        <div className="flex items-center gap-2 shrink-0">
          {recording.status === 'failed' && user?.role !== 'participant' && (
            <button
              onClick={() => retryMutation.mutate()}
              disabled={retryMutation.isPending}
              className="btn-warning"
            >
              <RefreshCw className="h-4 w-4" />
              Reîncearcă
            </button>
          )}

          {recording.status === 'completed' && (
            <div className="relative" ref={exportRef}>
              <button
                onClick={() => setExportOpen(v => !v)}
                aria-haspopup="menu"
                aria-expanded={exportOpen}
                className="btn-secondary"
              >
                <Download className="h-4 w-4" />
                Export
                <ChevronDown className={`h-3.5 w-3.5 transition-transform duration-150 ${exportOpen ? 'rotate-180' : ''}`} />
              </button>
              {exportOpen && (
                <div
                  className="absolute right-0 mt-1.5 w-44 bg-white border border-slate-200 rounded-xl shadow-lg shadow-slate-900/10 z-10 py-1 animate-fade-in"
                  role="menu"
                  aria-label="Formate export"
                >
                  {EXPORT_FORMATS.map(fmt => (
                    <button
                      key={fmt.value}
                      role="menuitem"
                      onClick={() => handleExport(fmt.value)}
                      className="block w-full text-left px-4 py-2.5 text-sm text-slate-700 hover:bg-slate-50 transition-colors"
                    >
                      {fmt.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {user?.is_admin && (
            <Tooltip content="Șterge înregistrarea">
              <button
                onClick={() => setShowDeleteDialog(true)}
                disabled={deleteMutation.isPending}
                className="btn-ghost text-slate-400 hover:text-rose-500 hover:bg-rose-50"
                aria-label="Șterge înregistrarea"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </Tooltip>
          )}
        </div>
      </div>

      {/* Metadata */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        <MetaItem icon={<Calendar className="h-4 w-4" />} label="Data ședinței"
          value={new Date(recording.meeting_date).toLocaleDateString('ro-RO', { day: 'numeric', month: 'short', year: 'numeric' })} />
        <MetaItem icon={<Clock className="h-4 w-4" />} label="Durată"
          value={recording.duration_formatted} />
        <MetaItem icon={<FileAudio className="h-4 w-4" />} label="Fișier"
          value={`${recording.file_size_mb.toFixed(1)} MB`} />
        {recording.location && (
          <MetaItem icon={<MapPin className="h-4 w-4" />} label="Locație"
            value={recording.location} />
        )}
        {recording.participants && recording.participants.length > 0 && (
          <div className="col-span-2 sm:col-span-4 bg-slate-50 rounded-xl p-3.5 border border-slate-200">
            <div className="flex items-center gap-2 mb-1.5">
              <Users className="h-4 w-4 text-slate-400" />
              <span className="text-xs text-slate-500 font-medium">Participanți</span>
            </div>
            <p className="text-sm text-slate-700">{recording.participants.join(', ')}</p>
          </div>
        )}
      </div>

      {/* Participanți cu acces — admin și operator */}
      {canManageParticipants && (
        <div className="card p-4 mb-6">
          <div className="flex items-center gap-2 mb-3">
            <Users className="h-4 w-4 text-slate-400" />
            <h2 className="text-sm font-semibold text-slate-700">Participanți cu acces</h2>
          </div>
          <ParticipantLinker
            recordingId={id!}
            linked={resolvedParticipants ?? recording.resolved_participants ?? []}
          />
        </div>
      )}

      {/* Audio Player — sticky */}
      {recording.status === 'completed' && (
        <div className="sticky top-0 z-10 bg-slate-50/95 backdrop-blur-sm py-3 -mx-6 px-6 border-b border-slate-200 mb-6 shadow-sm">
          <AudioPlayer
            ref={audioPlayerRef}
            recordingId={id!}
            onTimeUpdate={setCurrentTime}
          />
        </div>
      )}

      {/* Transcript */}
      <div className="card overflow-hidden">
        <div className="px-5 py-3.5 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
          <h2 className="text-sm font-semibold text-slate-700">Transcript</h2>
          <div className="flex items-center gap-3">
            {transcript && (
              <span className="text-xs text-slate-400">
                {transcript.word_count} cuvinte · {transcript.language?.toUpperCase()}
              </span>
            )}
            {transcript && transcript.segments && (
              <button
                onClick={() => {
                  const text = transcript.segments.map((segment: Segment) => segment.text).join('\n')
                  navigator.clipboard.writeText(text)
                  setCopied(true)
                  setTimeout(() => setCopied(false), 2000)
                }}
                className="inline-flex items-center gap-1 text-xs font-medium transition-colors text-primary-600 hover:text-primary-700"
                aria-label="Copiază transcriptul complet"
              >
                {copied ? (
                  <>
                    <Check className="h-3.5 w-3.5 text-emerald-500" />
                    <span className="text-emerald-500">Copiat!</span>
                  </>
                ) : (
                  'Copiază tot'
                )}
              </button>
            )}
          </div>
        </div>

        <div className="p-5">
          {isProcessing && (
            <TranscriptionProgress
              status={recording.status as 'queued' | 'transcribing'}
            />
          )}

          {recording.status === 'failed' && (
            <div className="py-8 text-center">
              <p className="text-rose-500 text-sm font-medium">Transcrierea nu a putut fi finalizată.</p>
              {recording.error_message && (
                <p className="text-slate-400 text-xs mt-1.5">{recording.error_message}</p>
              )}
            </div>
          )}

          {txLoading && (
            <div className="flex justify-center py-8"><Spinner className="h-6 w-6" /></div>
          )}

          {transcript && transcript.segments && (
            <TranscriptViewer
              segments={transcript.segments}
              currentTime={currentTime}
              onSegmentClick={(t) => audioPlayerRef.current?.seek(t)}
            />
          )}

          {recording.status === 'completed' && !txLoading && !transcript && (
            <p className="text-center text-slate-400 text-sm py-8">Transcrierea nu este disponibilă.</p>
          )}
        </div>
      </div>

      {/* Dialog confirmare ștergere */}
      {user?.is_admin && showDeleteDialog && (
        <ConfirmDialog
          open={showDeleteDialog}
          title="Șterge înregistrarea?"
          description={`"${recording.title}" va fi ștearsă permanent. Transcriptul și fișierul audio nu pot fi recuperate.`}
          confirmLabel="Șterge permanent"
          danger
          onConfirm={() => deleteMutation.mutate()}
          onClose={() => setShowDeleteDialog(false)}
        />
      )}
    </div>
  )
}

function MetaItem({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="bg-slate-50 border border-slate-200 rounded-xl p-3.5">
      <div className="flex items-center gap-1.5 mb-1.5 text-slate-400">
        {icon}
        <span className="text-xs font-medium text-slate-500">{label}</span>
      </div>
      <p className="text-sm font-semibold text-slate-800 truncate" title={value}>{value}</p>
    </div>
  )
}
