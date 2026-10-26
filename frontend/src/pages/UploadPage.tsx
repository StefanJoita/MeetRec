import { useCallback, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getUploadConfig } from '@/api/admin'
import { requestNotificationPermission } from '@/hooks/useTranscriptionNotifications'
import { UploadCloud, FileAudio, X, ArrowLeft, CheckCircle, AlertCircle } from 'lucide-react'
import { useUploadQueue, type UploadItem } from '@/hooks/useUploadQueue'
import MeetingDetailsForm, { emptyMeetingDetails, trimmedDetails } from '@/components/recording/MeetingDetailsForm'
import { cn } from '@/lib/cn'

const FORMATS = ['mp3', 'wav', 'm4a', 'ogg', 'flac', 'webm']
const ACCEPTED = FORMATS.map(f => `.${f}`).join(',')
const DEFAULT_MAX_MB = 500

const mb = (bytes: number) => `${(bytes / 1024 / 1024).toFixed(1)} MB`

function ItemRow({ item, onRemove, removable }: { item: UploadItem; onRemove: () => void; removable: boolean }) {
  return (
    <li className="flex items-center gap-3 px-4 py-3">
      <FileAudio className={cn('h-5 w-5 shrink-0', item.status === 'error' ? 'text-red-400' : 'text-blue-500')} />
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline justify-between gap-3">
          <p className="text-sm font-medium text-gray-900 truncate">{item.file.name}</p>
          <span className="text-xs text-gray-400 shrink-0">{mb(item.file.size)}</span>
        </div>
        {item.status === 'uploading' && (
          <div className="mt-1.5 h-1.5 bg-gray-200 rounded-full overflow-hidden">
            <div className="h-1.5 bg-blue-600 rounded-full transition-all duration-300" style={{ width: `${item.progress}%` }}
                 role="progressbar" aria-valuenow={item.progress} aria-label={`Încărcare ${item.file.name}`} />
          </div>
        )}
        {item.status === 'error' && (
          <p className="text-xs text-red-600 mt-0.5">
            {item.error}
            {item.duplicateOf && (
              <Link to={`/recordings/${item.duplicateOf}`} className="ml-1 font-medium underline">Deschide înregistrarea</Link>
            )}
          </p>
        )}
      </div>
      <span className="text-xs shrink-0 w-24 text-right">
        {item.status === 'pending' && <span className="text-gray-500">În așteptare</span>}
        {item.status === 'uploading' && <span className="text-blue-600 font-medium">{item.progress}%</span>}
        {item.status === 'done' && <span className="text-green-600 font-medium inline-flex items-center gap-1"><CheckCircle className="h-3.5 w-3.5" /> Trimis</span>}
        {item.status === 'error' && <span className="text-red-600 font-medium inline-flex items-center gap-1"><AlertCircle className="h-3.5 w-3.5" /> Eroare</span>}
      </span>
      {removable && (
        <button type="button" onClick={onRemove} className="p-1 rounded text-gray-400 hover:text-red-500 shrink-0"
                aria-label={`Elimină ${item.file.name}`}>
          <X className="h-4 w-4" />
        </button>
      )}
    </li>
  )
}

export default function UploadPage() {
  const navigate = useNavigate()
  // Limita e setabilă din Administrare → Setări; serverul o verifică oricum (413)
  const { data: uploadConfig } = useQuery({ queryKey: ['upload-config'], queryFn: getUploadConfig, staleTime: 60_000 })
  const MAX_MB = uploadConfig ? Math.floor(uploadConfig.max_file_size_bytes / (1024 * 1024)) : DEFAULT_MAX_MB
  const [dragging, setDragging] = useState(false)
  const [details, setDetails] = useState(emptyMeetingDetails)
  const { items, running, add, remove, clear, start, cancel } = useUploadQueue()

  const check = useCallback((f: File) => {
    const ext = f.name.split('.').pop()?.toLowerCase() ?? ''
    if (!FORMATS.includes(ext)) return `Formatul .${ext} nu e acceptat. Formate acceptate: ${FORMATS.join(', ').toUpperCase()}.`
    if (f.size > MAX_MB * 1024 * 1024) return `Fișierul depășește limita de ${MAX_MB} MB.`
    return ''
  }, [MAX_MB])

  const addFiles = useCallback((files: FileList | null) => {
    if (files?.length) add(Array.from(files), check)
  }, [add, check])

  const pending = items.filter(it => it.status === 'pending').length
  const sent = items.filter(it => it.status === 'done').length
  const failed = items.filter(it => it.status === 'error').length
  const finished = !running && items.length > 0 && pending === 0 && sent > 0
  const uploadingIndex = items.filter(it => it.status === 'done' || it.status === 'uploading').length
  const multiple = items.filter(it => it.status !== 'error').length > 1

  function handleUpload() {
    requestNotificationPermission()   // notificare de sistem când transcrierea e gata
    const meta = trimmedDetails(details)
    // La mai multe fișiere, fiecare primește ca titlu numele lui (Ingest)
    void start(() => (multiple ? { ...meta, title: undefined } : meta))
  }

  function reset() {
    clear()
    setDetails(emptyMeetingDetails())
  }

  return (
    <div className="p-6 max-w-xl mx-auto">
      <button
        onClick={() => navigate(-1)}
        className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 mb-6"
      >
        <ArrowLeft className="h-4 w-4" /> Înapoi
      </button>

      <h1 className="page-title mb-1">Încarcă fișiere</h1>
      <p className="text-sm text-gray-500 mb-6">
        Trimiteți la transcriere înregistrări făcute deja (reportofon, telefon, alt program). Puteți selecta mai multe fișiere deodată.
      </p>

      {finished && (
        <div className="mb-6 border border-green-200 bg-green-50 rounded-xl px-5 py-4">
          <p className="text-sm font-semibold text-green-800 flex items-center gap-2">
            <CheckCircle className="h-4 w-4" />
            {sent === 1 ? 'Un fișier trimis' : `${sent} fișiere trimise`} la transcriere
            {failed > 0 && <span className="text-red-700 font-medium">· {failed} cu eroare</span>}
          </p>
          <p className="text-xs text-green-800/80 mt-1">
            Apar în lista de înregistrări după validare. Un fișier respins la validare apare acolo ca „Eșuat”, cu motivul.
          </p>
          <div className="flex gap-2 mt-3">
            <button onClick={() => navigate('/')} className="btn-primary">Vezi lista de înregistrări</button>
            <button onClick={reset} className="btn-secondary">Încarcă alte fișiere</button>
          </div>
        </div>
      )}

      {/* Dropzone */}
      {!running && !finished && (
        <div
          onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer.files) }}
          onClick={() => document.getElementById('file-input')?.click()}
          className={cn(
            'border-2 border-dashed rounded-xl text-center transition-all cursor-pointer',
            items.length ? 'p-5' : 'p-10',
            dragging ? 'border-blue-400 bg-blue-50 cursor-copy' : 'border-gray-300 hover:border-gray-400'
          )}
        >
          <input
            id="file-input"
            type="file"
            accept={ACCEPTED}
            multiple
            className="hidden"
            onChange={(e) => { addFiles(e.target.files); e.target.value = '' }}
          />
          <UploadCloud className={cn('text-gray-300 mx-auto', items.length ? 'h-7 w-7 mb-1.5' : 'h-12 w-12 mb-3')} />
          <p className="text-sm font-medium text-gray-700">
            {items.length ? 'Adăugați alte fișiere' : 'Glisați fișierele aici sau '}
            {!items.length && <span className="text-blue-600">selectați-le</span>}
          </p>
          <p className="text-xs text-gray-400 mt-1">{FORMATS.join(', ').toUpperCase()} · max {MAX_MB} MB fiecare</p>
        </div>
      )}

      {items.length > 0 && (
        <ul className="mt-4 border border-slate-200 rounded-xl divide-y divide-slate-100 bg-white" aria-label="Fișiere de încărcat">
          {items.map(item => (
            <ItemRow key={item.id} item={item} onRemove={() => remove(item.id)}
                     removable={!running && item.status !== 'uploading' && item.status !== 'done'} />
          ))}
        </ul>
      )}

      {!finished && (
        <>
          <div className="mt-6">
            <MeetingDetailsForm
              value={details}
              onChange={setDetails}
              disabled={running}
              titleNote={multiple
                ? 'Fiecare fișier primește ca titlu numele lui; îl puteți schimba după încărcare. Celelalte detalii se aplică tuturor fișierelor.'
                : undefined}
            />
          </div>

          {running ? (
            <div className="mt-6 flex gap-3">
              <button type="button" disabled className="btn-primary flex-1 justify-center">
                Se trimite {uploadingIndex} din {uploadingIndex + pending}…
              </button>
              <button type="button" onClick={cancel} className="btn-secondary">Anulează</button>
            </div>
          ) : (
            <button
              type="button"
              onClick={handleUpload}
              disabled={pending === 0}
              className="btn-primary mt-6 w-full justify-center"
            >
              {pending > 1 ? `Trimite ${pending} fișiere la transcriere` : 'Trimite la transcriere'}
            </button>
          )}
        </>
      )}
    </div>
  )
}
