// Pagina „Încarcă fișiere”: mai multe fișiere deodată, trimise pe rând, fiecare
// cu rezultatul lui; fișierele prea mari sau cu format greșit sunt marcate înainte de trimitere.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import UploadPage from '@/pages/UploadPage'

const http = vi.hoisted(() => ({ post: vi.fn() }))
vi.mock('@/api/client', () => ({ default: http }))
vi.mock('@/api/admin', () => ({ getUploadConfig: vi.fn().mockResolvedValue({ max_file_size_bytes: 1024 * 1024 }) }))

const audio = (name: string, bytes = 10) => new File([new Uint8Array(bytes)], name, { type: 'audio/mp4' })

function renderPage() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <UploadPage />
      </MemoryRouter>
    </QueryClientProvider>
  )
  return document.getElementById('file-input') as HTMLInputElement
}

/** Nivelul de clasificare e obligatoriu înainte de trimitere. */
async function chooseClassification(user: ReturnType<typeof userEvent.setup>, code = 'SSv') {
  await user.selectOptions(screen.getByLabelText(/^Nivel de clasificare/), code)
}

const sentNames = () => http.post.mock.calls.map(([, form]) => ((form as FormData).get('file') as File).name)
const sentField = (i: number, key: string) => (http.post.mock.calls[i][1] as FormData).get(key)

beforeEach(() => {
  http.post.mockReset()
  http.post.mockResolvedValue({ data: {} })
})

describe('Încărcare fișiere', () => {
  it('mai multe fișiere: trimise pe rând, fiecare cu numele lui ca titlu, detaliile comune pentru toate', async () => {
    const user = userEvent.setup()
    const input = renderPage()
    await screen.findByText(/max 1 MB fiecare/)

    await user.upload(input, [audio('Voce 1.m4a'), audio('Voce 2.m4a'), audio('Conferinta.mp3')])
    expect(screen.getAllByText('În așteptare')).toHaveLength(3)
    // Titlul comun nu are sens la mai multe fișiere
    expect(screen.queryByLabelText('Titlu')).not.toBeInTheDocument()
    expect(screen.getByText(/Fiecare fișier primește ca titlu numele lui/)).toBeInTheDocument()

    await user.type(screen.getByLabelText('Locație'), 'Sala Mare')
    await chooseClassification(user)
    await user.click(screen.getByRole('button', { name: 'Trimite 3 fișiere la transcriere' }))

    expect(await screen.findByText(/3 fișiere trimise la transcriere/)).toBeInTheDocument()
    expect(sentNames()).toEqual(['Voce 1.m4a', 'Voce 2.m4a', 'Conferinta.mp3'])
    expect(sentField(0, 'location')).toBe('Sala Mare')
    expect(sentField(2, 'location')).toBe('Sala Mare')
    expect(sentField(0, 'title')).toBeNull()
    expect(sentField(0, 'classification')).toBe('SSv')
    expect(sentField(2, 'classification')).toBe('SSv')
    expect(screen.getAllByText('Trimis')).toHaveLength(3)
  })

  it('un singur fișier: titlul din formular e trimis', async () => {
    const user = userEvent.setup()
    const input = renderPage()
    await user.upload(input, audio('a.m4a'))
    await user.type(screen.getByLabelText('Titlu'), 'Ședința CA')
    await chooseClassification(user)
    await user.click(screen.getByRole('button', { name: 'Trimite la transcriere' }))

    expect(await screen.findByText(/Un fișier trimis la transcriere/)).toBeInTheDocument()
    expect(sentField(0, 'title')).toBe('Ședința CA')
  })

  it('fișier prea mare sau cu format greșit: marcat imediat, netrimis; celelalte pleacă', async () => {
    const user = userEvent.setup({ applyAccept: false })
    const input = renderPage()
    await screen.findByText(/max 1 MB fiecare/)

    await user.upload(input, [audio('mare.wav', 2 * 1024 * 1024), audio('video.avi'), audio('bun.m4a')])
    const list = screen.getByRole('list', { name: 'Fișiere de încărcat' })
    expect(within(list).getByText('Fișierul depășește limita de 1 MB.')).toBeInTheDocument()
    expect(within(list).getByText(/Formatul \.avi nu e acceptat/)).toBeInTheDocument()

    await chooseClassification(user)
    await user.click(screen.getByRole('button', { name: 'Trimite la transcriere' }))
    expect(await screen.findByText(/Un fișier trimis la transcriere/)).toBeInTheDocument()
    expect(sentNames()).toEqual(['bun.m4a'])
    expect(screen.getByText(/2 cu eroare/)).toBeInTheDocument()
  })

  it('fișier deja încărcat (409): eroare cu link spre înregistrare, coada continuă', async () => {
    http.post
      .mockRejectedValueOnce({ response: { status: 409, data: { detail: { message: 'Fișierul a fost deja încărcat: „X”.', recording_id: 'rec-1' } } } })
      .mockResolvedValueOnce({ data: {} })
    const user = userEvent.setup()
    const input = renderPage()
    await user.upload(input, [audio('dublura.m4a'), audio('nou.m4a')])
    await chooseClassification(user)
    await user.click(screen.getByRole('button', { name: 'Trimite 2 fișiere la transcriere' }))

    expect(await screen.findByText(/Un fișier trimis la transcriere/)).toBeInTheDocument()
    expect(screen.getByText('Fișierul a fost deja încărcat: „X”.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Deschide înregistrarea' })).toHaveAttribute('href', '/recordings/rec-1')
  })

  it('același fișier adăugat de două ori apare o singură dată; fișierele pot fi eliminate înainte de trimitere', async () => {
    const user = userEvent.setup()
    const input = renderPage()
    await user.upload(input, audio('a.m4a'))
    await user.upload(input, [audio('a.m4a'), audio('b.m4a')])
    expect(screen.getAllByText('În așteptare')).toHaveLength(2)

    await user.click(screen.getByRole('button', { name: 'Elimină a.m4a' }))
    expect(screen.queryByText('a.m4a')).not.toBeInTheDocument()
    expect(screen.getByText('b.m4a')).toBeInTheDocument()
  })

  it('anulare: fișierul în curs și cele rămase revin „în așteptare”', async () => {
    http.post.mockImplementation((_url, _form, { signal }) => new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(Object.assign(new Error('canceled'), { name: 'CanceledError' })))
    }))
    const user = userEvent.setup()
    const input = renderPage()
    await user.upload(input, [audio('a.m4a'), audio('b.m4a')])
    await chooseClassification(user)
    await user.click(screen.getByRole('button', { name: 'Trimite 2 fișiere la transcriere' }))
    await screen.findByText(/Se trimite 1 din 2/)

    await user.click(screen.getByRole('button', { name: 'Anulează' }))
    await waitFor(() => expect(screen.getAllByText('În așteptare')).toHaveLength(2))
    expect(http.post).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: 'Trimite 2 fișiere la transcriere' })).toBeEnabled()
  })

  it('fără nivel de clasificare nu se trimite nimic', async () => {
    const user = userEvent.setup()
    const input = renderPage()
    await user.upload(input, audio('a.m4a'))

    expect(screen.getByRole('button', { name: 'Alegeți nivelul de clasificare' })).toBeDisabled()
    expect(screen.getByLabelText(/^Nivel de clasificare/)).toHaveValue('')

    await chooseClassification(user, 'SS')
    expect(screen.getByLabelText(/^Nivel de clasificare/)).toHaveValue('SS')
    await user.click(screen.getByRole('button', { name: 'Trimite la transcriere' }))
    expect(await screen.findByText(/Un fișier trimis la transcriere/)).toBeInTheDocument()
    expect(sentField(0, 'classification')).toBe('SS')
  })
})
