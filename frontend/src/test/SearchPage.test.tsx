// src/test/SearchPage.test.tsx
// Căutare: pornește la Enter (nu la fiecare tastă), rezultate grupate pe ședință,
// potriviri în titlu, link la momentul fragmentului, paginare, filtru vorbitor.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import SearchPage from '@/pages/SearchPage'
import type { CombinedSearchResponse, CombinedSearchResult } from '@/api/types'

const api = vi.hoisted(() => ({ searchCombined: vi.fn(), getSearchSpeakers: vi.fn() }))
vi.mock('@/api/search', () => api)

function hit(overrides: Partial<CombinedSearchResult> = {}): CombinedSearchResult {
  return {
    recording_id: 'rec-1', recording_title: 'Ședința CA', meeting_date: '2026-10-01', segment_id: 'seg-1',
    start_time: 125.5, end_time: 130, text: 'Votăm bugetul pe 2027.', headline: 'Votăm <b>bugetul</b> pe 2027.',
    rank: 0.1, similarity: 0.7, source: 'both', score: 0.03, speaker_id: 'SPEAKER_00', speaker_name: 'Ion Popescu',
    ...overrides,
  }
}

function response(overrides: Partial<CombinedSearchResponse> = {}): CombinedSearchResponse {
  return {
    query: 'buget',
    groups: [{ recording_id: 'rec-1', recording_title: 'Ședința CA', meeting_date: '2026-10-01', score: 0.03,
               total_hits: 5, hits: [hit()] }],
    recordings: [{ recording_id: 'rec-2', title: 'Buget local 2027', meeting_date: '2026-09-01',
                   location: 'Sala Mare', headline: '<b>Buget</b> local 2027' }],
    total_groups: 1, total_hits: 5, page: 1, page_size: 10, pages: 1,
    fts_count: 3, semantic_count: 4, both_count: 2, semantic_available: true, search_time_ms: 40,
    ...overrides,
  }
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter><SearchPage /></MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('SearchPage', () => {
  beforeEach(() => {
    api.searchCombined.mockReset().mockResolvedValue(response())
    api.getSearchSpeakers.mockReset().mockResolvedValue([])
  })

  it('caută doar la Enter, nu la fiecare tastă', async () => {
    renderPage()
    const input = screen.getByLabelText('Caută în transcrieri')

    await userEvent.type(input, 'buget')
    expect(api.searchCombined).not.toHaveBeenCalled()

    await userEvent.type(input, '{enter}')
    expect(api.searchCombined).toHaveBeenCalledTimes(1)
    expect(api.searchCombined).toHaveBeenCalledWith('buget', 1, {})
  })

  it('grupează pe ședință, arată vorbitorul și duce la momentul fragmentului', async () => {
    renderPage()
    await userEvent.type(screen.getByLabelText('Caută în transcrieri'), 'buget{enter}')

    expect(await screen.findByText('5 fragmente în 1 ședințe')).toBeInTheDocument()
    expect(screen.getByText('Ion Popescu')).toBeInTheDocument()
    expect(screen.getByText('2:05').closest('a')).toHaveAttribute('href', '/recordings/rec-1?t=125.5')
    expect(screen.getByText('încă 4 fragmente în această ședință')).toBeInTheDocument()
    expect(screen.getByText('Ședințe găsite după titlu sau detalii')).toBeInTheDocument()
    expect(screen.getByText('Buget local 2027').closest('a')).toHaveAttribute('href', '/recordings/rec-2')
  })

  it('anunță când căutarea după sens nu e disponibilă', async () => {
    api.searchCombined.mockResolvedValue(response({ semantic_available: false }))
    renderPage()
    await userEvent.type(screen.getByLabelText('Caută în transcrieri'), 'buget{enter}')

    expect(await screen.findByText(/Căutarea după sens nu este disponibilă/)).toBeInTheDocument()
  })

  it('paginează pe ședințe', async () => {
    api.searchCombined.mockResolvedValue(response({ pages: 3, total_groups: 25 }))
    renderPage()
    await userEvent.type(screen.getByLabelText('Caută în transcrieri'), 'buget{enter}')
    await screen.findByText('Ion Popescu')

    await userEvent.click(screen.getByRole('button', { name: '2' }))

    await waitFor(() => expect(api.searchCombined).toHaveBeenLastCalledWith('buget', 2, {}))
  })

  it('filtrează după vorbitor', async () => {
    api.getSearchSpeakers.mockResolvedValue([{ id: 'u-1', name: 'Ion Popescu' }])
    renderPage()
    await userEvent.type(screen.getByLabelText('Caută în transcrieri'), 'buget{enter}')
    await screen.findByText('5 fragmente în 1 ședințe')

    await userEvent.click(screen.getByRole('button', { name: /Filtre/ }))
    await userEvent.selectOptions(await screen.findByLabelText('Vorbitor'), 'u-1')

    await waitFor(() => expect(api.searchCombined).toHaveBeenLastCalledWith('buget', 1, { speaker: 'u-1' }))
  })
})
