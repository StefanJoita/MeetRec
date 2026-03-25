import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { Mic2, Eye, EyeOff, AlertCircle } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'

interface LoginForm {
  username: string
  password: string
}

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [showPass, setShowPass] = useState(false)
  const [error, setError] = useState('')

  const { register, handleSubmit, formState: { isSubmitting } } = useForm<LoginForm>()

  async function onSubmit(data: LoginForm) {
    setError('')
    try {
      await login(data.username, data.password)
      navigate('/')
    } catch {
      setError('Nume de utilizator sau parolă incorectă.')
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 p-4 relative overflow-hidden">
      {/* Background decorative blobs */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-40 -right-40 w-96 h-96 bg-primary-100 rounded-full opacity-60 blur-3xl" />
        <div className="absolute -bottom-40 -left-40 w-96 h-96 bg-indigo-100 rounded-full opacity-40 blur-3xl" />
      </div>

      <div className="w-full max-w-[380px] relative animate-slide-up">
        {/* Card */}
        <div className="bg-white rounded-2xl shadow-xl ring-1 ring-slate-900/5 p-8">
          {/* Logo */}
          <div className="flex flex-col items-center mb-8">
            <div className="h-14 w-14 bg-primary-600 rounded-2xl flex items-center justify-center mb-4 shadow-lg shadow-primary-600/25">
              <Mic2 className="h-7 w-7 text-white" />
            </div>
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight">MeetRec</h1>
            <p className="text-slate-500 text-sm mt-1">Sistem de transcriere ședințe</p>
          </div>

          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <div>
              <label htmlFor="username-input" className="block text-sm font-medium text-slate-700 mb-1.5">
                Utilizator
              </label>
              <input
                id="username-input"
                {...register('username', { required: true })}
                type="text"
                autoComplete="username"
                className="input-base"
                placeholder="Nume utilizator"
              />
            </div>

            <div>
              <label htmlFor="password-input" className="block text-sm font-medium text-slate-700 mb-1.5">
                Parolă
              </label>
              <div className="relative">
                <input
                  id="password-input"
                  {...register('password', { required: true })}
                  type={showPass ? 'text' : 'password'}
                  autoComplete="current-password"
                  className="input-base pr-10"
                  placeholder="••••••••"
                />
                <button
                  type="button"
                  onClick={() => setShowPass(!showPass)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 transition-colors"
                  tabIndex={-1}
                >
                  {showPass ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>

            {error && (
              <div className="flex items-center gap-2.5 bg-rose-50 border border-rose-200 rounded-lg px-4 py-3 text-sm text-rose-700">
                <AlertCircle className="h-4 w-4 shrink-0" />
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full btn-primary justify-center py-3 mt-2"
            >
              {isSubmitting ? 'Se conectează...' : 'Conectare'}
            </button>
          </form>
        </div>

        <p className="text-center text-xs text-slate-400 mt-4">
          MeetRec · Transcrieri locale și securizate
        </p>
      </div>
    </div>
  )
}
