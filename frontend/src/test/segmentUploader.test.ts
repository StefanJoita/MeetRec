// Coada de segmente a înregistrării din browser: ordine, reîncercări la căderea
// serverului, segmente respinse definitiv, așteptarea golirii cozii la oprire.
import { describe, it, expect, vi } from 'vitest'
import { SegmentUploader, isPermanentError, type UploaderStatus } from '@/lib/recording/segmentUploader'

const blob = () => new Blob(['x'])
const httpError = (status: number, detail?: string) => Object.assign(new Error('http'), {
  response: { status, data: detail ? { detail } : {} },
})

describe('SegmentUploader', () => {
  it('trimite segmentele pe rând, în ordinea indexului', async () => {
    const sent: number[] = []
    let release!: () => void
    const first = new Promise<void>(r => { release = r })
    const upload = vi.fn(async (i: number) => {
      if (i === 0) await first
      sent.push(i)
    })
    const u = new SegmentUploader({ upload })
    u.enqueue(0, blob())
    u.enqueue(1, blob())
    u.enqueue(2, blob())
    expect(upload).toHaveBeenCalledTimes(1)   // al doilea pleacă doar după primul
    release()
    await u.drain()
    expect(sent).toEqual([0, 1, 2])
  })

  it('serverul nu răspunde: reîncearcă același segment până reușește, fără să-l piardă', async () => {
    const statuses: UploaderStatus[] = []
    const upload = vi.fn()
      .mockRejectedValueOnce(new Error('Network Error'))
      .mockRejectedValueOnce(httpError(503))
      .mockResolvedValue(undefined)
    const sleep = vi.fn(async (_ms: number) => {})
    const u = new SegmentUploader({ upload, sleep, onChange: s => statuses.push(s) })

    u.enqueue(0, blob())
    await u.drain()

    expect(upload).toHaveBeenCalledTimes(3)
    expect(upload.mock.calls.every(([i]) => i === 0)).toBe(true)
    expect(sleep.mock.calls.map(([ms]) => ms)).toEqual([2_000, 5_000])
    expect(statuses.some(s => s.retrying)).toBe(true)
    expect(statuses[statuses.length - 1]).toMatchObject({ uploaded: 1, pending: 0, failed: 0, retrying: false, lastError: '' })
  })

  it('segment respins de server (4xx): trece mai departe și raportează eroarea', async () => {
    const upload = vi.fn()
      .mockRejectedValueOnce(httpError(413, 'Fișierul depășește limita de 1 MB.'))
      .mockResolvedValue(undefined)
    const statuses: UploaderStatus[] = []
    const u = new SegmentUploader({ upload, sleep: async () => {}, onChange: s => statuses.push(s) })

    u.enqueue(0, blob())
    u.enqueue(1, blob())
    await u.drain()

    expect(upload).toHaveBeenCalledTimes(2)
    expect(statuses[statuses.length - 1]).toMatchObject({ uploaded: 1, failed: 1, pending: 0 })
    expect(statuses.some(s => s.lastError === 'Fișierul depășește limita de 1 MB.')).toBe(true)
  })

  it('drain() pe coadă goală se rezolvă imediat', async () => {
    await expect(new SegmentUploader({ upload: vi.fn() }).drain()).resolves.toBeUndefined()
  })

  it('stop() oprește reîncercările și eliberează drain()', async () => {
    let wake!: () => void
    const sleep = vi.fn(() => new Promise<void>(r => { wake = r }))
    const upload = vi.fn().mockRejectedValue(new Error('Network Error'))
    const u = new SegmentUploader({ upload, sleep })

    u.enqueue(0, blob())
    const drained = u.drain()
    await vi.waitFor(() => expect(sleep).toHaveBeenCalled())
    u.stop()
    wake()
    await drained
    expect(upload).toHaveBeenCalledTimes(1)
  })
})

describe('isPermanentError', () => {
  it.each([
    [httpError(400), true],
    [httpError(413), true],
    [httpError(408), false],
    [httpError(429), false],
    [httpError(500), false],
    [new Error('Network Error'), false],
  ])('%#', (e, expected) => {
    expect(isPermanentError(e)).toBe(expected)
  })
})
