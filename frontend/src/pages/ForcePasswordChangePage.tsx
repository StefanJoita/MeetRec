import { useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { Mic2 } from 'lucide-react'
import { Navigate } from 'react-router-dom'

import { changePasswordFirstLogin } from '@/api/auth'
import { useAuth } from '@/contexts/AuthContext'

interface PasswordForm {
  currentPassword: string
  newPassword: string
  confirmPassword: string
}

function passwordStrength(pw: string): { score: number; label: string; color: string } {
  if (!pw) return { score: 0, label: '', color: '' }
  let score = 0
  if (pw.length >= 8) score++
  if (pw.length >= 12) score++
  if (/[A-Z]/.test(pw)) score++
  if (/[0-9]/.test(pw)) score++
  if (/[^A-Za-z0-9]/.test(pw)) score++
  if (score <= 1) return { score, label: 'Slabă', color: 'bg-rose-500' }
  if (score <= 2) return { score, label: 'Acceptabilă', color: 'bg-amber-400' }
  if (score <= 3) return { score, label: 'Bună', color: 'bg-yellow-400' }
  if (score === 4) return { score, label: 'Puternică', color: 'bg-emerald-500' }
  return { score, label: 'Excelentă', color: 'bg-emerald-600' }
}

export default function ForcePasswordChangePage() {
  const { user, refreshUser } = useAuth()
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const { register, handleSubmit, formState: { isSubmitting, errors }, control, getValues } = useForm<PasswordForm>()
  const newPassword = useWatch({ control, name: 'newPassword', defaultValue: '' })
  const strength = passwordStrength(newPassword)

  async function onSubmit(data: PasswordForm) {
    setError('')
    setSuccess('')

    try {
      await changePasswordFirstLogin(data.currentPassword, data.newPassword)
      await refreshUser()
      setSuccess('Parola a fost schimbată. Poți continua în aplicație.')
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Nu am putut schimba parola. Încearcă din nou.')
    }
  }

  if (!user?.must_change_password) {
    return <Navigate to="/" replace />
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-8">
        <div className="flex flex-col items-center mb-8">
          <div className="h-14 w-14 bg-blue-600 rounded-2xl flex items-center justify-center mb-4 shadow-md">
            <Mic2 className="h-7 w-7 text-white" />
          </div>
          <h1 className="text-2xl font-bold text-gray-900">Schimbare parolă</h1>
          <p className="text-gray-500 text-sm mt-1 text-center">
            Pentru securitate, trebuie să schimbi parola temporară înainte de a continua.
          </p>
        </div>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">Parolă curentă</label>
            <input
              {...register('currentPassword', { required: 'Parola curentă este obligatorie.' })}
              type="password"
              autoComplete="current-password"
              className={`w-full px-3.5 py-2.5 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${errors.currentPassword ? 'border-red-400' : 'border-gray-300'}`}
            />
            {errors.currentPassword && (
              <p className="mt-1.5 text-xs text-red-600">{errors.currentPassword.message}</p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">Parolă nouă</label>
            <input
              {...register('newPassword', {
                required: 'Parola nouă este obligatorie.',
                minLength: { value: 8, message: 'Parola trebuie să aibă cel puțin 8 caractere.' },
              })}
              type="password"
              autoComplete="new-password"
              className={`w-full px-3.5 py-2.5 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${errors.newPassword ? 'border-red-400' : 'border-gray-300'}`}
            />
            {errors.newPassword && (
              <p className="mt-1.5 text-xs text-red-600">{errors.newPassword.message}</p>
            )}
            {newPassword && (
              <div className="mt-2 space-y-1">
                <div className="flex gap-1">
                  {[1, 2, 3, 4, 5].map(i => (
                    <div
                      key={i}
                      className={`h-1 flex-1 rounded-full transition-all duration-300 ${
                        i <= strength.score ? strength.color : 'bg-gray-200'
                      }`}
                    />
                  ))}
                </div>
                <p className={`text-xs font-medium ${
                  strength.score <= 1 ? 'text-rose-500'
                  : strength.score <= 2 ? 'text-amber-500'
                  : strength.score <= 3 ? 'text-yellow-600'
                  : 'text-emerald-600'
                }`}>
                  {strength.label}
                </p>
              </div>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">Confirmă parola nouă</label>
            <input
              {...register('confirmPassword', {
                required: 'Confirmarea parolei este obligatorie.',
                validate: value => value === getValues('newPassword') || 'Parolele noi nu coincid.',
              })}
              type="password"
              autoComplete="new-password"
              className={`w-full px-3.5 py-2.5 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${errors.confirmPassword ? 'border-red-400' : 'border-gray-300'}`}
            />
            {errors.confirmPassword && (
              <p className="mt-1.5 text-xs text-red-600">{errors.confirmPassword.message}</p>
            )}
          </div>

          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}

          {success && (
            <div className="bg-green-50 border border-green-200 rounded-lg px-4 py-3 text-sm text-green-700">
              {success}
            </div>
          )}

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white font-medium py-2.5 rounded-lg text-sm transition-colors"
          >
            {isSubmitting ? 'Se salvează...' : 'Schimbă parola'}
          </button>
        </form>
      </div>
    </div>
  )
}
