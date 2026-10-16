import client from '@/api/client'

export type SettingValue = number | boolean | null

export interface AppSetting {
  key: string
  group: string
  label: string
  description: string
  applies: string
  type: 'int' | 'bool' | 'optional_int'
  min: number | null
  max: number | null
  unit: string | null
  value: SettingValue
  env_value: SettingValue
  source: 'interfata' | 'env'
  updated_at: string | null
  updated_by: string | null
}

export interface WorkerStatus {
  worker_id: string
  whisper_model: string
  whisper_threads: number
  diarization_enabled: boolean
  diarization_parallel: boolean
  current_recording_id: string | null
  started_at: number
  updated_at: number
}

export interface SystemStatus {
  version: string | null
  whisper_model_configured: string | null
  queue: {
    available: boolean
    queued: number | null
    processing: number | null
    workers: WorkerStatus[]
  }
  search_index: { available: boolean; model: string | null; pending_segments: number | null }
  disk: { total_bytes: number; used_bytes: number; free_bytes: number } | null
  recordings_by_status: Record<string, number>
  recent_failures: { id: string; title: string; error_message: string | null; updated_at: string | null }[]
}

export interface ProcessingItem {
  recording_id: string
  title: string
  completed_at: string | null
  model_used: string | null
  audio_sec: number | null
  processing_sec: number
  ratio: number | null
  transcription_sec: number | null
  alignment_sec: number | null
  diarization_sec: number | null
  diarization_parallel: boolean
}

export type ProcessingSort = 'recent' | 'slowest'

export interface ProcessingPage {
  items: ProcessingItem[]
  total: number
  page: number
  page_size: number
  pages: number
  summary: { count: number; audio_sec: number; processing_sec: number; ratio: number | null }
}

export async function getSettings(): Promise<AppSetting[]> {
  const { data } = await client.get<AppSetting[]>('/admin/settings')
  return data
}

export async function updateSetting(key: string, value: SettingValue): Promise<AppSetting[]> {
  const { data } = await client.put<AppSetting[]>(`/admin/settings/${key}`, { value })
  return data
}

export async function resetSetting(key: string): Promise<AppSetting[]> {
  const { data } = await client.delete<AppSetting[]>(`/admin/settings/${key}`)
  return data
}

export async function getSystemStatus(): Promise<SystemStatus> {
  const { data } = await client.get<SystemStatus>('/admin/system')
  return data
}

export async function getUploadConfig(): Promise<{ max_file_size_bytes: number }> {
  const { data } = await client.get<{ max_file_size_bytes: number }>('/config/upload')
  return data
}

export async function getProcessingTimes(page: number, sort: ProcessingSort): Promise<ProcessingPage> {
  const { data } = await client.get<ProcessingPage>('/admin/processing', { params: { page, sort } })
  return data
}

// ── Coada de transcriere ─────────────────────────────────────

export interface QueueItem {
  recording_id: string
  title: string | null          // null = înregistrarea a fost ștearsă
  duration_seconds: number | null
  status: string | null
  created_at: string | null
  jobs: number                  // sesiune multi-fișier: mai multe joburi
}

export interface RunningQueueItem extends QueueItem {
  worker_id: string
  worker_alive: boolean
  progress: Record<string, number>   // {"transcriere": 100, "aliniere": 40}
  cancelling: boolean
  cancel_requested: boolean
}

export interface TranscriptionQueue {
  available: boolean
  running: RunningQueueItem[]
  waiting: QueueItem[]
}

export async function getQueue(): Promise<TranscriptionQueue> {
  const { data } = await client.get<TranscriptionQueue>('/admin/queue')
  return data
}

export async function cancelTranscription(recordingId: string): Promise<{ removed: number; running: boolean }> {
  const { data } = await client.post<{ removed: number; running: boolean }>(`/admin/queue/${recordingId}/cancel`)
  return data
}

export async function prioritizeTranscription(recordingId: string): Promise<void> {
  await client.post(`/admin/queue/${recordingId}/prioritize`)
}
