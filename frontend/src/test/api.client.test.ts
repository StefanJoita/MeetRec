// src/test/api.client.test.ts
// Teste pentru clientul Axios — configurație și interceptori JWT.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('API client — configurație statică', () => {
  it('are baseURL /api/v1', async () => {
    const { default: client } = await import('@/api/client')
    expect(client.defaults.baseURL).toBe('/api/v1')
  })

  it('are Content-Type application/json', async () => {
    const { default: client } = await import('@/api/client')
    expect(client.defaults.headers['Content-Type']).toBe('application/json')
  })

  it('are interceptori de request înregistrați', async () => {
    const { default: client } = await import('@/api/client')
    // axios stochează handlerii în interceptors.request.handlers
    // (filtrăm null care apar după eject)
    const handlers = (client.interceptors.request as unknown as { handlers: unknown[] }).handlers
    const active = handlers.filter(Boolean)
    expect(active.length).toBeGreaterThan(0)
  })

  it('are interceptori de response înregistrați (pentru redirect 401)', async () => {
    const { default: client } = await import('@/api/client')
    const handlers = (client.interceptors.response as unknown as { handlers: unknown[] }).handlers
    const active = handlers.filter(Boolean)
    expect(active.length).toBeGreaterThan(0)
  })
})

describe('API client — interceptor JWT', () => {
  it('adaugă header Authorization la request când există token', async () => {
    localStorage.setItem('access_token', 'test-token-xyz')

    // Testăm direct logica interceptorului: construim un config fake
    // și apelăm manual handler-ul de request.
    const { default: client } = await import('@/api/client')
    const handlers = (client.interceptors.request as unknown as {
      handlers: Array<{ fulfilled: (config: Record<string, unknown>) => Record<string, unknown> } | null>
    }).handlers

    const jwtHandler = handlers.filter(Boolean)[0]!
    const fakeConfig = { headers: {} as Record<string, string> }
    const result = jwtHandler.fulfilled(fakeConfig)

    expect((result.headers as Record<string, string>).Authorization).toBe('Bearer test-token-xyz')
  })

  it('nu adaugă header Authorization când nu există token', async () => {
    // localStorage e gol (curățat în beforeEach)
    const { default: client } = await import('@/api/client')
    const handlers = (client.interceptors.request as unknown as {
      handlers: Array<{ fulfilled: (config: Record<string, unknown>) => Record<string, unknown> } | null>
    }).handlers

    const jwtHandler = handlers.filter(Boolean)[0]!
    const fakeConfig = { headers: {} as Record<string, string> }
    const result = jwtHandler.fulfilled(fakeConfig)

    expect((result.headers as Record<string, string>).Authorization).toBeUndefined()
  })

  it('interceptorul de response șterge token-ul la 401', async () => {
    localStorage.setItem('access_token', 'token-valid')
    vi.stubGlobal('window', { ...window, location: { href: '' } })

    const { default: client } = await import('@/api/client')
    const handlers = (client.interceptors.response as unknown as {
      handlers: Array<{ rejected: (error: unknown) => unknown } | null>
    }).handlers

    const responseHandler = handlers.filter(Boolean)[0]!
    const fakeError = { response: { status: 401 } }

    try {
      await responseHandler.rejected(fakeError)
    } catch {
      // rejected handler rearuncă eroarea
    }

    expect(localStorage.getItem('access_token')).toBeNull()
  })
})
