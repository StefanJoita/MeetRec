// Coada de trimitere a segmentelor înregistrării din browser.
// Segmentele pleacă pe rând, în ordinea indexului (Ingest leagă segmentul 0 de
// sesiunea pre-înregistrată, celelalte se atașează după el). Dacă rețeaua sau
// serverul pică, segmentul rămâne în memorie și se reîncearcă la nesfârșit,
// cu pauze crescătoare; înregistrarea continuă între timp.

export interface UploaderStatus {
  uploaded: number
  pending: number
  failed: number            // segmente respinse definitiv de server (4xx)
  retrying: boolean         // ultima încercare a eșuat, se reîncearcă
  lastError: string
}

export interface UploaderDeps {
  upload: (index: number, blob: Blob) => Promise<void>
  sleep?: (ms: number) => Promise<void>
  onChange?: (status: UploaderStatus) => void
}

const RETRY_DELAYS_MS = [2_000, 5_000, 10_000, 30_000]

/** Erori 4xx (în afară de timeout / prea multe cereri) nu se rezolvă reîncercând. */
export function isPermanentError(e: unknown): boolean {
  const status = (e as { response?: { status?: number } })?.response?.status
  return status !== undefined && status >= 400 && status < 500 && status !== 408 && status !== 429
}

export function errorMessage(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof detail === 'string' ? detail : fallback
}

export class SegmentUploader {
  private queue: { index: number; blob: Blob }[] = []
  private running = false
  private stopped = false
  private idleWaiters: Array<() => void> = []
  private status: UploaderStatus = { uploaded: 0, pending: 0, failed: 0, retrying: false, lastError: '' }
  private readonly sleep: (ms: number) => Promise<void>

  constructor(private readonly deps: UploaderDeps) {
    this.sleep = deps.sleep ?? (ms => new Promise(r => setTimeout(r, ms)))
  }

  enqueue(index: number, blob: Blob): void {
    this.queue.push({ index, blob })
    this.update({ pending: this.queue.length })
    void this.run()
  }

  /** Așteaptă trimiterea tuturor segmentelor din coadă. */
  drain(): Promise<void> {
    if (!this.running && this.queue.length === 0) return Promise.resolve()
    return new Promise(resolve => this.idleWaiters.push(resolve))
  }

  /** Oprește reîncercările (la închiderea înregistrării fără trimitere). */
  stop(): void {
    this.stopped = true
    this.queue = []
    this.update({ pending: 0, retrying: false })
    this.resolveIdle()
  }

  private async run(): Promise<void> {
    if (this.running) return
    this.running = true
    try {
      while (this.queue.length > 0 && !this.stopped) {
        const item = this.queue[0]
        let attempt = 0
        for (;;) {
          try {
            await this.deps.upload(item.index, item.blob)
            this.queue.shift()
            this.update({ uploaded: this.status.uploaded + 1, pending: this.queue.length, retrying: false, lastError: '' })
            break
          } catch (e) {
            if (this.stopped) return
            if (isPermanentError(e)) {
              this.queue.shift()
              this.update({
                failed: this.status.failed + 1, pending: this.queue.length, retrying: false,
                lastError: errorMessage(e, `Segmentul ${item.index + 1} a fost respins de server.`),
              })
              break
            }
            this.update({ retrying: true, lastError: 'Serverul nu răspunde. Segmentele se păstrează și se retrimit automat.' })
            await this.sleep(RETRY_DELAYS_MS[Math.min(attempt++, RETRY_DELAYS_MS.length - 1)])
            if (this.stopped) return
          }
        }
      }
    } finally {
      this.running = false
      if (this.queue.length === 0 || this.stopped) this.resolveIdle()
    }
  }

  private resolveIdle(): void {
    const waiters = this.idleWaiters
    this.idleWaiters = []
    waiters.forEach(w => w())
  }

  private update(patch: Partial<UploaderStatus>): void {
    this.status = { ...this.status, ...patch }
    this.deps.onChange?.(this.status)
  }
}
