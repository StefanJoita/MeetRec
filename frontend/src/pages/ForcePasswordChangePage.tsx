import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Mic2 } from 'lucide-react'
import { Navigate } from 'react-router-dom'

import { changePasswordFirstLogin } from '@/api/auth'
import { useAuth } from '@/contexts/AuthContext'

interface PasswordForm {
  currentPassword: string
  newPassword: string
  confirmPassword: string
}

export default function ForcePasswordChangePage() {
  const { user, refreshUser } = useAuth()
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const { register, handleSubmit, formState: { isSubmitting } } = useForm<PasswordForm>()

  async function onSubmit(data: PasswordForm) {
    setError('')
    setSuccess('')

    if (data.newPassword !== data.confirmPassword) {
      setError('Parolele noi nu coincid.')
      return
    }

    try {
      await changePasswordFirstLogin(data.currentPassword, data.newPassword)
      await refreshUser()
      setSuccess('Parola a fost schimbată. Poți continua în aplicație.')
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Nu am putut schimba parola.')
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
              {...register('currentPassword', { required: true })}
              type="password"
              autoComplete="current-password"
              className="w-full px-3.5 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">Parolă nouă</label>
            <input
              {...register('newPassword', { required: true, minLength: 8 })}
              type="password"
              autoComplete="new-password"
              className="w-full px-3.5 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">Confirmă parola nouă</label>
            <input
              {...register('confirmPassword', { required: true, minLength: 8 })}
              type="password"
              autoComplete="new-password"
              className="w-full px-3.5 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
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
