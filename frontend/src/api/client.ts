import axios from 'axios'
import { logoutEventEmitter } from '@/contexts/AuthContext'

const client = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
})

// Attach JWT to every request
client.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// If API returns 401 → emit logout event (handled by AuthProvider)
client.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('access_token')
      logoutEventEmitter.emit()
    }
    return Promise.reject(err)
  }
)

export default client
