import client from './client'
import type { TokenResponse, User } from './types'

export async function login(username: string, password: string): Promise<TokenResponse> {
  const { data } = await client.post<TokenResponse>('/auth/login', { username, password })
  return data
}

export async function getMe(): Promise<User> {
  const { data } = await client.get<User>('/auth/me')
  return data
}

export async function logout(): Promise<void> {
  await client.post('/auth/logout')
}

export async function changePasswordFirstLogin(current_password: string, new_password: string): Promise<void> {
  await client.post('/auth/change-password-first-login', { current_password, new_password })
}
