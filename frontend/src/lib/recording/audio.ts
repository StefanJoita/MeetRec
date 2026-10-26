// Procesarea audio a înregistrării din browser: reducere la 16 kHz,
// împărțire fără pauze în segmente și codare WAV PCM 16 biți mono.
//
// De ce WAV și nu MediaRecorder (WebM/Opus)?
//   - fragmentele MediaRecorder nu sunt fișiere de sine stătătoare (doar primul
//     are antet), iar repornirea lui la fiecare segment lasă goluri;
//   - Ingest măsoară durata cu mutagen, care nu citește WebM.
// 16 kHz e rata la care lucrează oricum Whisper, alinierea și diarizarea:
// ~1,9 MB pe minut, ~9,6 MB pe segment de 5 minute.

export const TARGET_SAMPLE_RATE = 16_000
export const SEGMENT_SECONDS = 300
// Ingest respinge fișierele sub 5 secunde (validator.py)
export const MIN_SEGMENT_SECONDS = 5

/** Reduce rata de eșantionare în flux (medie pe fiecare fereastră → filtru anti-aliasing simplu). */
export class Downsampler {
  // Pozițiile se numără în întregi (pași de outputRate per eșantion de intrare,
  // un eșantion de ieșire la fiecare inputRate): fără erori de rotunjire cumulate
  private acc = 0
  private count = 0
  private pos = 0
  private last = 0

  constructor(private readonly inputRate: number, private readonly outputRate = TARGET_SAMPLE_RATE) {
    this.inputRate = Math.round(inputRate)
  }

  process(input: Float32Array): Float32Array {
    const out: number[] = []
    for (let i = 0; i < input.length; i++) {
      this.acc += input[i]
      this.count++
      this.pos += this.outputRate
      while (this.pos >= this.inputRate) {
        if (this.count > 0) {
          this.last = this.acc / this.count
          this.acc = 0
          this.count = 0
        }
        out.push(this.last)   // rată de intrare < 16 kHz: se repetă eșantionul
        this.pos -= this.inputRate
      }
    }
    return Float32Array.from(out)
  }
}

/**
 * Float → Int16 cu dither TPDF (±1 LSB, inaudibil). Pe lângă calitate, face ca două
 * segmente de liniște digitală (microfon dezactivat) să nu fie identice: Ingest
 * respinge fișierele cu același SHA-256 ca duplicate.
 */
export function toInt16(samples: Float32Array, random: () => number = Math.random): Int16Array {
  const out = new Int16Array(samples.length)
  for (let i = 0; i < samples.length; i++) {
    const v = Math.round(samples[i] * 32767 + (random() - random()))
    out[i] = Math.max(-32768, Math.min(32767, v))
  }
  return out
}

/** Acumulează eșantioane de 16 kHz și le taie exact la fiecare SEGMENT_SECONDS. */
export class SegmentBuffer {
  private chunks: Int16Array[] = []
  private length = 0
  private readonly segmentSamples: number

  constructor(segmentSeconds = SEGMENT_SECONDS, private readonly sampleRate = TARGET_SAMPLE_RATE) {
    this.segmentSamples = segmentSeconds * sampleRate
  }

  /** Adaugă eșantioane; întoarce segmentele complete (de obicei niciunul). */
  push(samples: Int16Array): Int16Array[] {
    const done: Int16Array[] = []
    let offset = 0
    while (offset < samples.length) {
      const take = Math.min(this.segmentSamples - this.length, samples.length - offset)
      this.chunks.push(samples.subarray(offset, offset + take))
      this.length += take
      offset += take
      if (this.length === this.segmentSamples) done.push(this.take())
    }
    return done
  }

  /**
   * Ultimul segment, la oprire. Un rest sub MIN_SEGMENT_SECONDS e completat cu
   * liniște, altfel Ingest l-ar respinge. Fără eșantioane (oprire exact la limita
   * unui segment) → null, cu excepția cazului `force` (sesiune fără niciun segment).
   */
  flush(force = false): Int16Array | null {
    if (this.length === 0 && !force) return null
    const min = MIN_SEGMENT_SECONDS * this.sampleRate
    if (this.length < min) {
      this.chunks.push(toInt16(new Float32Array(min - this.length)))
      this.length = min
    }
    return this.take()
  }

  get bufferedSeconds(): number {
    return this.length / this.sampleRate
  }

  private take(): Int16Array {
    const out = new Int16Array(this.length)
    let at = 0
    for (const c of this.chunks) {
      out.set(c, at)
      at += c.length
    }
    this.chunks = []
    this.length = 0
    return out
  }
}

/** Fișier WAV (RIFF, PCM 16 biți, mono). */
export function encodeWav(samples: Int16Array, sampleRate = TARGET_SAMPLE_RATE): Blob {
  const header = new ArrayBuffer(44)
  const v = new DataView(header)
  const text = (at: number, s: string) => { for (let i = 0; i < s.length; i++) v.setUint8(at + i, s.charCodeAt(i)) }
  const dataBytes = samples.length * 2

  text(0, 'RIFF')
  v.setUint32(4, 36 + dataBytes, true)
  text(8, 'WAVE')
  text(12, 'fmt ')
  v.setUint32(16, 16, true)            // mărimea blocului fmt
  v.setUint16(20, 1, true)             // PCM
  v.setUint16(22, 1, true)             // mono
  v.setUint32(24, sampleRate, true)
  v.setUint32(28, sampleRate * 2, true) // octeți pe secundă
  v.setUint16(32, 2, true)             // octeți pe cadru
  v.setUint16(34, 16, true)            // biți pe eșantion
  text(36, 'data')
  v.setUint32(40, dataBytes, true)

  // WAV e little-endian, ca toate platformele pe care rulează browserele
  return new Blob([header, samples.buffer.slice(samples.byteOffset, samples.byteOffset + dataBytes) as ArrayBuffer],
                  { type: 'audio/wav' })
}

/** Nivelul semnalului (0–1) pentru indicatorul de volum: RMS scalat, ca vorbirea să fie vizibilă. */
export function signalLevel(samples: Float32Array): number {
  if (samples.length === 0) return 0
  let sum = 0
  for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i]
  return Math.min(1, Math.sqrt(sum / samples.length) * 4)
}
