// Înregistrarea din browser: reducerea la 16 kHz, tăierea fără pauze în
// segmente și fișierele WAV acceptate de Ingest.
import { describe, it, expect } from 'vitest'
import { Downsampler, encodeWav, SegmentBuffer, signalLevel, toInt16 } from '@/lib/recording/audio'

const noDither = () => 0.5   // random() - random() = 0

async function bytes(blob: Blob): Promise<DataView> {
  // jsdom: Blob fără arrayBuffer() în unele versiuni → FileReader
  const buf: ArrayBuffer = await new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => resolve(r.result as ArrayBuffer)
    r.onerror = () => reject(r.error)
    r.readAsArrayBuffer(blob)
  })
  return new DataView(buf)
}

function ascii(v: DataView, at: number, n: number): string {
  return Array.from({ length: n }, (_, i) => String.fromCharCode(v.getUint8(at + i))).join('')
}

describe('Downsampler', () => {
  it('48 kHz → 16 kHz: o treime din eșantioane, media fiecărei ferestre', () => {
    const d = new Downsampler(48_000, 16_000)
    const out = d.process(Float32Array.from([0.3, 0.6, 0.9, -0.3, -0.6, -0.9]))
    expect(out.length).toBe(2)
    expect(out[0]).toBeCloseTo(0.6)
    expect(out[1]).toBeCloseTo(-0.6)
  })

  it('păstrează starea între blocuri (blocuri care nu se împart exact)', () => {
    const d = new Downsampler(44_100, 16_000)
    let total = 0
    for (let i = 0; i < 100; i++) total += d.process(new Float32Array(441)).length
    expect(total).toBe(16_000)   // exact o secundă, fără eșantioane pierdute la granițe
  })

  it('rată de intrare egală: semnalul trece neschimbat', () => {
    const d = new Downsampler(16_000, 16_000)
    expect(Array.from(d.process(Float32Array.from([0.1, 0.2])))).toEqual([
      expect.closeTo(0.1), expect.closeTo(0.2),
    ])
  })
})

describe('toInt16', () => {
  it('scalează și limitează la intervalul pe 16 biți', () => {
    expect(Array.from(toInt16(Float32Array.from([0, 1, -1, 2, -2]), noDither)))
      .toEqual([0, 32767, -32767, 32767, -32768])
  })

  it('liniștea digitală nu dă fișiere identice (Ingest respinge duplicatele după SHA-256)', () => {
    const a = toInt16(new Float32Array(16_000))
    const b = toInt16(new Float32Array(16_000))
    expect(a.some((v, i) => v !== b[i])).toBe(true)
    expect(Math.max(...a.map(Math.abs))).toBeLessThanOrEqual(1)
  })
})

describe('SegmentBuffer', () => {
  it('taie exact la durata segmentului, restul trece în segmentul următor', () => {
    const buf = new SegmentBuffer(1, 10)            // segmente de 10 eșantioane
    expect(buf.push(new Int16Array(7))).toEqual([])
    const done = buf.push(Int16Array.from({ length: 8 }, (_, i) => i + 1))
    expect(done).toHaveLength(1)
    expect(Array.from(done[0])).toEqual([0, 0, 0, 0, 0, 0, 0, 1, 2, 3])
    expect(buf.bufferedSeconds).toBeCloseTo(0.5)
  })

  it('un bloc mai lung decât un segment produce mai multe segmente', () => {
    const buf = new SegmentBuffer(1, 10)
    expect(buf.push(new Int16Array(25))).toHaveLength(2)
    expect(buf.bufferedSeconds).toBeCloseTo(0.5)
  })

  it('ultimul segment sub 5 secunde e completat cu liniște (minimul cerut de Ingest)', () => {
    const buf = new SegmentBuffer(300, 16_000)
    buf.push(new Int16Array(16_000).fill(1000))       // 1 secundă
    const last = buf.flush()!
    expect(last.length).toBe(5 * 16_000)
    expect(last[0]).toBe(1000)
    expect(Math.abs(last[last.length - 1])).toBeLessThanOrEqual(1)
  })

  it('oprire exact la limita unui segment: nu se mai trimite un segment gol', () => {
    const buf = new SegmentBuffer(1, 16_000)
    buf.push(new Int16Array(16_000))
    expect(buf.flush()).toBeNull()
    expect(buf.flush(true)!.length).toBe(5 * 16_000)  // sesiune fără niciun segment
  })
})

describe('encodeWav', () => {
  it('antet RIFF/WAVE PCM 16 biți mono, cu mărimile corecte', async () => {
    const samples = Int16Array.from([1, -2, 3])
    const blob = encodeWav(samples, 16_000)
    expect(blob.type).toBe('audio/wav')
    expect(blob.size).toBe(44 + 6)

    const v = await bytes(blob)
    expect(ascii(v, 0, 4)).toBe('RIFF')
    expect(v.getUint32(4, true)).toBe(36 + 6)
    expect(ascii(v, 8, 4)).toBe('WAVE')
    expect(ascii(v, 12, 4)).toBe('fmt ')
    expect(v.getUint16(20, true)).toBe(1)        // PCM
    expect(v.getUint16(22, true)).toBe(1)        // mono
    expect(v.getUint32(24, true)).toBe(16_000)
    expect(v.getUint16(34, true)).toBe(16)
    expect(ascii(v, 36, 4)).toBe('data')
    expect(v.getUint32(40, true)).toBe(6)
    expect([v.getInt16(44, true), v.getInt16(46, true), v.getInt16(48, true)]).toEqual([1, -2, 3])
  })

  it('un subarray scrie doar eșantioanele lui, nu tot bufferul de dedesubt', async () => {
    const all = Int16Array.from([9, 9, 5, 6, 9])
    const v = await bytes(encodeWav(all.subarray(2, 4)))
    expect(v.byteLength).toBe(48)
    expect([v.getInt16(44, true), v.getInt16(46, true)]).toEqual([5, 6])
  })
})

describe('signalLevel', () => {
  it('0 pe liniște, limitat la 1 pe semnal puternic', () => {
    expect(signalLevel(new Float32Array(128))).toBe(0)
    expect(signalLevel(new Float32Array(128).fill(0.9))).toBe(1)
    expect(signalLevel(new Float32Array(0))).toBe(0)
  })
})
