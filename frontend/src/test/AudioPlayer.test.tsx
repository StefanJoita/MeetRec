// src/test/AudioPlayer.test.tsx
// Durata din player: unele MP4-uri raportează NaN/Infinity → se folosește durata din baza de date.
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import AudioPlayer from '@/components/AudioPlayer'
import { formatTime } from '@/lib/formatTime'

vi.mock('@/api/recordings', () => ({
  getAudioToken: vi.fn().mockResolvedValue('tok'),
  buildAudioUrl: vi.fn(() => '/api/v1/recordings/r1/audio?token=tok'),
}))

function audioElement(container: HTMLElement): HTMLAudioElement {
  return container.querySelector('audio') as HTMLAudioElement
}

describe('AudioPlayer', () => {
  it('durata necunoscută de browser (NaN) → durata din baza de date', async () => {
    const { container } = render(<AudioPlayer recordingId="r1" fallbackDuration={3900} />)
    const audio = audioElement(container)
    await waitFor(() => expect(audio.getAttribute('src')).toContain('token=tok'))

    Object.defineProperty(audio, 'duration', { configurable: true, value: NaN })
    fireEvent.loadedMetadata(audio)

    expect(screen.getByText('1:05:00')).toBeInTheDocument()
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument()
  })

  it('durata infinită (MP4 fragmentat) nu afișează NaN', async () => {
    const { container } = render(<AudioPlayer recordingId="r1" fallbackDuration={null} />)
    const audio = audioElement(container)

    Object.defineProperty(audio, 'duration', { configurable: true, value: Infinity })
    fireEvent.loadedMetadata(audio)

    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument()
  })

  it('durata validă din fișier are prioritate', async () => {
    const { container } = render(<AudioPlayer recordingId="r1" fallbackDuration={3900} />)
    const audio = audioElement(container)

    Object.defineProperty(audio, 'duration', { configurable: true, value: 125 })
    fireEvent.loadedMetadata(audio)

    expect(screen.getByText('2:05')).toBeInTheDocument()
  })
})

describe('formatTime', () => {
  it('valori invalide', () => {
    expect(formatTime(NaN)).toBe('--:--')
    expect(formatTime(Infinity)).toBe('--:--')
    expect(formatTime(65)).toBe('1:05')
  })
})
