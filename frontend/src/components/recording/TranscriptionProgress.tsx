import { useEffect, useState } from 'react'
import { Mic2, Clock } from 'lucide-react'

interface TranscriptionProgressProps {
  status: 'queued' | 'transcribing'
}

export default function TranscriptionProgress({ status }: TranscriptionProgressProps) {
  const [elapsed, setElapsed] = useState(0)

  // Contor "ultima actualizare"
  useEffect(() => {
    setElapsed(0)
    const id = setInterval(() => setElapsed(s => s + 1), 1000)
    return () => clearInterval(id)
  }, [status])

  const elapsedText =
    elapsed === 0 ? 'acum' :
    elapsed < 60  ? `acum ${elapsed}s` :
                    `acum ${Math.floor(elapsed / 60)}m`

  return (
    <div
      role="status"
      aria-live="polite"
      aria-label={status === 'queued' ? 'În așteptare transcriere' : 'Transcriere în curs'}
      className="flex flex-col items-center gap-4 py-12"
    >
      {/* Iconiță animată */}
      <div className="relative">
        <div className={`h-14 w-14 rounded-full flex items-center justify-center
          ${status === 'transcribing' ? 'bg-orange-100' : 'bg-yellow-100'}`}>
          <Mic2 className={`h-6 w-6 ${status === 'transcribing' ? 'text-orange-500' : 'text-yellow-600'}`} />
        </div>
        {/* Ping animat */}
        <span className={`absolute inset-0 rounded-full animate-ping opacity-30
          ${status === 'transcribing' ? 'bg-orange-400' : 'bg-yellow-400'}`}
        />
      </div>

      {/* Titlu */}
      <div className="text-center">
        <p className="text-sm font-semibold text-gray-800 mb-1">
          {status === 'queued' ? 'În așteptare transcriere...' : 'Transcriere în curs...'}
        </p>
        <p className="text-xs text-gray-500 max-w-xs leading-relaxed">
          {status === 'queued'
            ? 'Fișierul este în coadă. Transcrierea pornește când ajunge la procesare.'
            : 'Transcrierea este în curs. Durata poate varia în funcție de fișier și de încărcarea sistemului.'}
        </p>
      </div>

      {/* Bare animate */}
      <div className="flex items-end gap-1 h-8" aria-hidden="true">
        {[0.4, 0.7, 1, 0.6, 0.9, 0.5, 0.8].map((h, i) => (
          <div
            key={i}
            className={`w-1.5 rounded-full ${status === 'transcribing' ? 'bg-orange-400' : 'bg-yellow-400'}`}
            style={{
              height: `${h * 100}%`,
              animation: `pulse ${0.8 + i * 0.15}s ease-in-out infinite alternate`,
            }}
          />
        ))}
      </div>

      {/* Timestamp actualizare */}
      <div className="flex items-center gap-1.5 text-xs text-gray-400">
        <Clock className="h-3.5 w-3.5" />
        <span>Ultima verificare: {elapsedText}</span>
      </div>
    </div>
  )
}
