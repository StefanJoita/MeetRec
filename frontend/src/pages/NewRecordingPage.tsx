import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { UploadCloud, FileAudio, X, ArrowLeft, CheckCircle } from 'lucide-react'
import { useState } from 'react'
import { useUploadWithProgress } from '@/hooks/useUploadWithProgress'
import { cn } from '@/lib/cn'

const ACCEPTED = '.mp3,.wav,.m4a,.ogg,.flac,.webm'
const MAX_MB = 500

export default function NewRecordingPage() {
  const navigate = useNavigate()
  const [file, setFile] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const [fileError, setFileError] = useState('')
  const { progress, uploading, done, error, upload, cancel, reset } = useUploadWithProgress()

  const handleFile = useCallback((f: File) => {
    if (f.size > MAX_MB * 1024 * 1024) {
      setFileError(`Fișierul depășește ${MAX_MB} MB.`)
      return
    }
    setFile(f)
    setFileError('')
  }, [])

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const f = e.dataTransfer.files[0]
    if (f) handleFile(f)
  }, [handleFile])

  async function handleUpload() {
    if (!file) { setFileError('Selectați un fișier audio.'); return }
    await upload(file)
  }

  function handleCancel() {
    cancel()
    setFile(null)
    reset()
  }

  if (done) {
    return (
      <div className="p-6 max-w-md mx-auto text-center mt-16">
        <CheckCircle className="h-14 w-14 text-green-500 mx-auto mb-4" />
        <h2 className="text-xl font-semibold text-gray-900 mb-2">Fișier trimis cu succes</h2>
        <p className="text-sm text-gray-500 mb-6">
          Înregistrarea va apărea în listă după ce Ingest Service o validează și o
          pune în coadă de transcriere. Acest proces durează câteva secunde.
        </p>
        <div className="flex gap-3 justify-center">
          <button onClick={() => navigate('/')} className="btn-primary">
            Vezi lista de înregistrări
          </button>
          <button
            onClick={() => { setFile(null); reset() }}
            className="btn-secondary"
          >
            Trimite alt fișier
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="p-6 max-w-xl mx-auto">
      <button
        onClick={() => navigate(-1)}
        className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 mb-6"
      >
        <ArrowLeft className="h-4 w-4" /> Înapoi
      </button>

      <h1 className="page-title mb-2">Înregistrare nouă</h1>
      <p className="text-sm text-gray-500 mb-6">
        Selectați fișierul audio. Ingest Service îl va valida, crea înregistrarea în baza
        de date și îl va trimite la transcriere automat.
      </p>

      {/* Dropzone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={cn(
          'relative border-2 rounded-xl p-10 text-center transition-all overflow-hidden',
          uploading
            ? 'border-blue-400 bg-blue-50 cursor-default'
            : dragging
              ? 'border-blue-400 bg-blue-50 border-dashed cursor-copy'
              : 'border-dashed border-gray-300 hover:border-gray-400 cursor-pointer'
        )}
        onClick={() => !file && !uploading && document.getElementById('file-input')?.click()}
      >
        <input
          id="file-input"
          type="file"
          accept={ACCEPTED}
          className="hidden"
          onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
        />

        {/* Starea: fișier selectat + upload în curs */}
        {uploading && file ? (
          <div className="space-y-4">
            <div className="flex items-center justify-center gap-3">
              <FileAudio className="h-6 w-6 text-blue-500 shrink-0" />
              <div className="text-left min-w-0">
                <p className="text-sm font-medium text-gray-900 truncate">{file.name}</p>
                <p className="text-xs text-gray-500">
                  {(file.size / 1024 / 1024).toFixed(1)} MB
                </p>
              </div>
            </div>

            {/* Bară progres */}
            <div>
              <div className="flex justify-between text-xs text-gray-500 mb-1">
                <span>Se încarcă...</span>
                <span>{progress}%</span>
              </div>
              <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
                <div
                  className="h-2 bg-blue-600 rounded-full transition-all duration-300"
                  style={{ width: `${progress}%` }}
                  aria-label={`Upload ${progress}%`}
                />
              </div>
            </div>

            <button
              type="button"
              onClick={handleCancel}
              className="text-xs text-red-500 hover:text-red-700 transition-colors"
            >
              Anulează upload
            </button>
          </div>

        ) : file ? (
          /* Fișier selectat, gata de upload */
          <div className="flex items-center justify-center gap-3">
            <FileAudio className="h-6 w-6 text-blue-500 shrink-0" />
            <div className="text-left min-w-0">
              <p className="text-sm font-medium text-gray-900 truncate">{file.name}</p>
              <p className="text-xs text-gray-500">{(file.size / 1024 / 1024).toFixed(1)} MB</p>
            </div>
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); setFile(null) }}
              className="ml-2 p-1 rounded text-gray-400 hover:text-red-500 shrink-0"
              aria-label="Elimină fișierul selectat"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

        ) : (
          /* Stare goală */
          <div>
            <UploadCloud className="h-12 w-12 text-gray-300 mx-auto mb-3" />
            <p className="text-sm font-medium text-gray-700">
              Glisați fișierul sau <span className="text-blue-600">selectați</span>
            </p>
            <p className="text-xs text-gray-400 mt-1">MP3, WAV, M4A, OGG, FLAC, WEBM · max {MAX_MB} MB</p>
          </div>
        )}
      </div>

      {/* Erori */}
      {(fileError || error) && (
        <div className="mt-4 bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
          {fileError || error}
        </div>
      )}

      <button
        type="button"
        onClick={handleUpload}
        disabled={!file || uploading}
        className="btn-primary mt-6 w-full justify-center"
      >
        {uploading ? `Se trimite... ${progress}%` : 'Trimite la transcriere'}
      </button>
    </div>
  )
}
