import { useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, Download, RefreshCw, Trash2,
  Calendar, Clock, MapPin, Users, FileAudio,
} from 'lucide-react'
import { getRecording, getAudioUrl, retryTranscription, deleteRecording } from '@/api/recordings'
import { getTranscript } from '@/api/transcripts'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { Spinner } from '@/components/ui/Spinner'
import AudioPlayer from '@/components/AudioPlayer'
import TranscriptViewer from '@/components/TranscriptViewer'

const EXPORT_FORMATS = [
  { value: 'txt', label: 'Text (.txt)' },
  { value: 'pdf', label: 'PDF (.pdf)' },
  { value: 'docx', label: 'Word (.docx)' },
]

export default function RecordingDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [currentTime, setCurrentTime] = useState(0)
  const [seekTo, setSeekTo] = useState<number | null>(null)

  const { data: recording, isLoading: recLoading } = useQuery({
    queryKey: ['recording', id],
    queryFn: () => getRecording(id!),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'queued' || status === 'transcribing' ? 5000 : false
    },
  })

  const { data: transcript, isLoading: txLoading } = useQuery({
    queryKey: ['transcript', id],
    queryFn: () => getTranscript(id!),
    enabled: recording?.status === 'completed',
    retry: false,
  })

  const retryMutation = useMutation({
    mutationFn: () => retryTranscription(id!),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['recording', id] }),
  })

  const deleteMutation = useMutation({
    mutationFn: () => deleteRecording(id!),
    onSuccess: () => navigate('/'),
  })

  function handleExport(format: string) {
    const token = localStorage.getItem('access_token') ?? ''
    window.open(`/api/v1/export/recording/${id}?format=${format}&token=${token}`, '_blank')
  }

  function handleDelete() {
    if (confirm('Ești sigur că vrei să ștergi această înregistrare? Acțiunea este ireversibilă.')) {
      deleteMutation.mutate()
    }
  }

  if (recLoading) {
    return <div className="flex justify-center py-24"><Spinner className="h-8 w-8" /></div>
  }

  if (!recording) {
    return (
      <div className="p-6 text-center">
        <p className="text-gray-500">Înregistrarea nu a fost găsită.</p>
        <Link to="/" className="text-blue-600 text-sm mt-2 inline-block">Înapoi la liste</Link>
      </div>
    )
  }

  const isProcessing = recording.status === 'queued' || recording.status === 'transcribing'

  return (
    <div className="p-6 max-w-5xl mx-auto">
      {/* Breadcrumb */}
      <button
        onClick={() => navigate(-1)}
        className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 mb-6"
      >
        <ArrowLeft className="h-4 w-4" /> Înapoi
      </button>

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4 mb-6">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 mb-2">
            <StatusBadge status={recording.status} />
            <span className="text-xs text-gray-400">{recording.audio_format.toUpperCase()}</span>
          </div>
          <h1 className="text-2xl font-bold text-gray-900 leading-tight">{recording.title}</h1>
          {recording.description && (
            <p className="text-gray-500 text-sm mt-1">{recording.description}</p>
          )}
        </div>

        {/* Acțiuni */}
        <div className="flex items-center gap-2 shrink-0">
          {recording.status === 'failed' && (
            <button
              onClick={() => retryMutation.mutate()}
              disabled={retryMutation.isPending}
              className="inline-flex items-center gap-2 px-3 py-2 border border-orange-300 text-orange-600 hover:bg-orange-50 rounded-lg text-sm font-medium transition-colors"
            >
              <RefreshCw className="h-4 w-4" />
              Retry
            </button>
          )}

          {recording.status === 'completed' && (
            <div className="relative group">
              <button className="inline-flex items-center gap-2 px-3 py-2 border border-gray-300 text-gray-700 hover:bg-gray-50 rounded-lg text-sm font-medium transition-colors">
                <Download className="h-4 w-4" />
                Export
              </button>
              <div className="absolute right-0 mt-1 w-36 bg-white border border-gray-200 rounded-lg shadow-lg opacity-0 group-hover:opacity-100 transition-opacity z-10">
                {EXPORT_FORMATS.map(fmt => (
                  <button
                    key={fmt.value}
                    onClick={() => handleExport(fmt.value)}
                    className="block w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 first:rounded-t-lg last:rounded-b-lg"
                  >
                    {fmt.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          <button
            onClick={handleDelete}
            disabled={deleteMutation.isPending}
            className="p-2 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"
            title="Șterge înregistrarea"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Metadata */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        <MetaItem icon={<Calendar className="h-4 w-4" />} label="Data ședinței"
          value={new Date(recording.meeting_date).toLocaleDateString('ro-RO')} />
        <MetaItem icon={<Clock className="h-4 w-4" />} label="Durată"
          value={recording.duration_formatted} />
        <MetaItem icon={<FileAudio className="h-4 w-4" />} label="Fișier"
          value={`${recording.file_size_mb.toFixed(1)} MB`} />
        {recording.location && (
          <MetaItem icon={<MapPin className="h-4 w-4" />} label="Locație"
            value={recording.location} />
        )}
        {recording.participants && recording.participants.length > 0 && (
          <div className="col-span-2 sm:col-span-4 bg-gray-50 rounded-xl p-3">
            <div className="flex items-center gap-2 mb-1">
              <Users className="h-4 w-4 text-gray-400" />
              <span className="text-xs text-gray-500 font-medium">Participanți</span>
            </div>
            <p className="text-sm text-gray-700">{recording.participants.join(', ')}</p>
          </div>
        )}
      </div>

      {/* Audio Player */}
      {recording.status === 'completed' && (
        <div className="mb-6">
          <AudioPlayer
            src={getAudioUrl(id!)}
            onTimeUpdate={setCurrentTime}
            seekTo={seekTo}
          />
        </div>
      )}

      {/* Transcript */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-700">Transcript</h2>
          {transcript && (
            <span className="text-xs text-gray-400">{transcript.word_count} cuvinte · {transcript.language}</span>
          )}
        </div>

        <div className="p-4">
          {isProcessing && (
            <div className="flex items-center gap-3 py-8 justify-center text-gray-500">
              <Spinner className="h-5 w-5" />
              <span className="text-sm">
                {recording.status === 'queued' ? 'În așteptare transcriere...' : 'Transcriere în curs...'}
              </span>
            </div>
          )}

          {recording.status === 'failed' && (
            <div className="py-8 text-center">
              <p className="text-red-500 text-sm">Transcrierea a eșuat.</p>
              {recording.error_message && (
                <p className="text-gray-400 text-xs mt-1">{recording.error_message}</p>
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
              onSegmentClick={(t) => setSeekTo(t)}
            />
          )}

          {recording.status === 'completed' && !txLoading && !transcript && (
            <p className="text-center text-gray-400 text-sm py-8">Transcriptul nu este disponibil.</p>
          )}
        </div>
      </div>
    </div>
  )
}

function MetaItem({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="bg-gray-50 rounded-xl p-3">
      <div className="flex items-center gap-1.5 mb-1 text-gray-400">{icon}<span className="text-xs font-medium">{label}</span></div>
      <p className="text-sm font-medium text-gray-800 truncate">{value}</p>
    </div>
  )
}
