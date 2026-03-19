import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { UploadCloud, FileAudio, X, ArrowLeft } from 'lucide-react'
import { createRecording, uploadAudio } from '@/api/recordings'
import { cn } from '@/lib/cn'

const ACCEPTED = '.mp3,.wav,.m4a,.ogg,.flac,.webm'
const MAX_MB = 500

interface FormValues {
  title: string
  meeting_date: string
  description?: string
  location?: string
  participants?: string
}

export default function NewRecordingPage() {
  const navigate = useNavigate()
  const [file, setFile] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState('')

  const { register, handleSubmit, formState: { errors } } = useForm<FormValues>({
    defaultValues: { meeting_date: new Date().toISOString().split('T')[0] },
  })

  const handleFile = useCallback((f: File) => {
    if (f.size > MAX_MB * 1024 * 1024) {
      setError(`Fișierul depășește ${MAX_MB} MB.`)
      return
    }
    setFile(f)
    setError('')
  }, [])

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const f = e.dataTransfer.files[0]
    if (f) handleFile(f)
  }, [handleFile])

  async function onSubmit(data: FormValues) {
    if (!file) { setError('Selectați un fișier audio.'); return }
    setUploading(true)
    setError('')
    try {
      const participants = data.participants
        ? data.participants.split(',').map(s => s.trim()).filter(Boolean)
        : undefined

      const recording = await createRecording({
        title: data.title,
        meeting_date: data.meeting_date,
        description: data.description,
        location: data.location,
        participants,
      })

      // Simulăm progress (uploadAudio nu are progress callback în MVP)
      const interval = setInterval(() => setProgress(p => Math.min(p + 10, 90)), 200)
      await uploadAudio(recording.id, file)
      clearInterval(interval)
      setProgress(100)

      navigate(`/recordings/${recording.id}`)
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Eroare la încărcare. Încercați din nou.')
      setUploading(false)
      setProgress(0)
    }
  }

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <button
        onClick={() => navigate(-1)}
        className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 mb-6"
      >
        <ArrowLeft className="h-4 w-4" /> Înapoi
      </button>

      <h1 className="text-2xl font-bold text-gray-900 mb-6">Înregistrare nouă</h1>

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
        {/* Dropzone */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">Fișier audio *</label>
          <div
            onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={cn(
              'relative border-2 border-dashed rounded-xl p-8 text-center transition-colors cursor-pointer',
              dragging ? 'border-blue-400 bg-blue-50' : 'border-gray-300 hover:border-gray-400'
            )}
            onClick={() => !file && document.getElementById('file-input')?.click()}
          >
            <input
              id="file-input"
              type="file"
              accept={ACCEPTED}
              className="hidden"
              onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
            />

            {file ? (
              <div className="flex items-center justify-center gap-3">
                <FileAudio className="h-6 w-6 text-blue-500" />
                <div className="text-left">
                  <p className="text-sm font-medium text-gray-900">{file.name}</p>
                  <p className="text-xs text-gray-500">{(file.size / 1024 / 1024).toFixed(1)} MB</p>
                </div>
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); setFile(null) }}
                  className="ml-2 p-1 rounded text-gray-400 hover:text-red-500"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            ) : (
              <div>
                <UploadCloud className="h-10 w-10 text-gray-300 mx-auto mb-3" />
                <p className="text-sm font-medium text-gray-700">Glisați fișierul sau <span className="text-blue-600">selectați</span></p>
                <p className="text-xs text-gray-400 mt-1">MP3, WAV, M4A, OGG, FLAC, WEBM · max {MAX_MB} MB</p>
              </div>
            )}
          </div>
        </div>

        {/* Titlu */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1.5">Titlu *</label>
          <input
            {...register('title', { required: 'Titlul este obligatoriu', minLength: { value: 3, message: 'Minim 3 caractere' } })}
            className="w-full px-3.5 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="Ședința Consiliului Local — 19 Martie 2026"
          />
          {errors.title && <p className="text-xs text-red-500 mt-1">{errors.title.message}</p>}
        </div>

        {/* Data */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1.5">Data ședinței *</label>
          <input
            {...register('meeting_date', { required: true })}
            type="date"
            className="w-full px-3.5 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        {/* Locație */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1.5">Locație</label>
          <input
            {...register('location')}
            className="w-full px-3.5 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="Sala de ședințe, Primăria..."
          />
        </div>

        {/* Participanți */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1.5">Participanți</label>
          <input
            {...register('participants')}
            className="w-full px-3.5 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="Ion Ionescu, Maria Pop, Andrei Radu"
          />
          <p className="text-xs text-gray-400 mt-1">Separați cu virgulă</p>
        </div>

        {/* Descriere */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1.5">Descriere</label>
          <textarea
            {...register('description')}
            rows={3}
            className="w-full px-3.5 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
            placeholder="Descriere opțională a ședinței..."
          />
        </div>

        {/* Progress */}
        {uploading && (
          <div>
            <div className="flex justify-between text-xs text-gray-500 mb-1">
              <span>Se încarcă...</span>
              <span>{progress}%</span>
            </div>
            <div className="h-2 bg-gray-200 rounded-full">
              <div
                className="h-2 bg-blue-600 rounded-full transition-all duration-300"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        )}

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={uploading}
          className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white font-medium py-2.5 rounded-lg text-sm transition-colors"
        >
          {uploading ? 'Se trimite...' : 'Trimite la transcriere'}
        </button>
      </form>
    </div>
  )
}
