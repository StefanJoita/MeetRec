import { Link } from 'react-router-dom'

export default function NotFoundPage() {
  return (
    <div className="flex flex-col items-center justify-center h-full py-24 text-center px-4">
      <p className="text-6xl font-bold text-gray-200 mb-4">404</p>
      <h1 className="text-xl font-semibold text-gray-800 mb-2">Pagina nu a fost găsită</h1>
      <p className="text-gray-500 text-sm mb-6">Adresa accesată nu există.</p>
      <Link to="/" className="bg-blue-600 hover:bg-blue-700 text-white px-5 py-2 rounded-lg text-sm font-medium transition-colors">
        Înapoi la înregistrări
      </Link>
    </div>
  )
}
