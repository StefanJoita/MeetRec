import { Link } from 'react-router-dom'
import { Home, ArrowLeft } from 'lucide-react'

export default function NotFoundPage() {
  return (
    <div className="flex flex-col items-center justify-center h-full py-20 text-center px-4 animate-page-in">

      {/* Ilustrație SVG */}
      <svg
        width="200"
        height="160"
        viewBox="0 0 200 160"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="mb-8 opacity-90"
        aria-hidden="true"
      >
        {/* Fundal cerc */}
        <circle cx="100" cy="80" r="72" fill="#EEF2FF" />

        {/* Document cu semn de întrebare */}
        <rect x="65" y="32" width="70" height="88" rx="8" fill="white" stroke="#C7D2FE" strokeWidth="2" />
        <rect x="75" y="48" width="34" height="5" rx="2.5" fill="#C7D2FE" />
        <rect x="75" y="60" width="50" height="5" rx="2.5" fill="#E0E7FF" />
        <rect x="75" y="72" width="42" height="5" rx="2.5" fill="#E0E7FF" />

        {/* Semn de întrebare */}
        <circle cx="100" cy="98" r="18" fill="#6366F1" />
        <text x="100" y="104" textAnchor="middle" fill="white" fontSize="18" fontWeight="700" fontFamily="system-ui">?</text>

        {/* Decorații mici */}
        <circle cx="40" cy="40" r="6" fill="#E0E7FF" />
        <circle cx="162" cy="120" r="8" fill="#C7D2FE" />
        <circle cx="155" cy="45" r="4" fill="#818CF8" opacity="0.4" />
        <circle cx="45" cy="118" r="5" fill="#818CF8" opacity="0.3" />
      </svg>

      {/* Text */}
      <span className="inline-block bg-primary-100 text-primary-700 text-xs font-bold tracking-widest uppercase px-3 py-1 rounded-full mb-4">
        Eroare 404
      </span>
      <h1 className="text-2xl font-bold text-slate-900 mb-2">
        Pagina nu a fost găsită
      </h1>
      <p className="text-slate-500 text-sm mb-8 max-w-xs leading-relaxed">
        Adresa accesată nu există sau a fost mutată. Verifică URL-ul sau întoarce-te la pagina principală.
      </p>

      {/* Acțiuni */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => history.back()}
          className="btn-secondary"
        >
          <ArrowLeft className="h-4 w-4" />
          Înapoi
        </button>
        <Link to="/" className="btn-primary">
          <Home className="h-4 w-4" />
          Înregistrări
        </Link>
      </div>
    </div>
  )
}
