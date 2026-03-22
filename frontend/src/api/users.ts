import client from '@/api/client'
import type { PaginatedUsers, UserCreate, UserUpdate, User } from '@/api/types'

export interface UsersParams {
  page?: number
  page_size?: number
  search?: string
  include_inactive?: boolean
}

export async function getUsers(params: UsersParams = {}): Promise<PaginatedUsers> {
  const { data } = await client.get<PaginatedUsers>('/users', { params })
  return data
}

export async function createUser(payload: UserCreate): Promise<User> {
  const { data } = await client.post<User>('/users', payload)
  return data
}

export async function updateUser(userId: string, payload: UserUpdate): Promise<User> {
  const { data } = await client.patch<User>(`/users/${userId}`, payload)
  return data
}

export async function deleteUser(userId: string): Promise<void> {
  await client.delete(`/users/${userId}`)
}

export async function resetUserPassword(userId: string, newPassword: string): Promise<void> {
  await client.post(`/users/${userId}/reset-password`, { new_password: newPassword })
}
