// AudioWorklet pentru înregistrarea din browser (src/contexts/RecorderContext.tsx).
// Rulează pe firul audio: amestecă canalele în mono și trimite blocuri de
// ~4096 de eșantioane Float32 la firul principal, care le reduce la 16 kHz
// și le împarte în segmente WAV. Importat cu `?url`: Vite îl copiază ca fișier
// separat, cu hash în nume (nginx ține fișierele .js în cache un an).

const BLOCK = 4096

class MeetRecRecorder extends AudioWorkletProcessor {
  constructor() {
    super()
    this.buffer = new Float32Array(BLOCK)
    this.filled = 0
  }

  process(inputs) {
    const channels = inputs[0]
    if (!channels || channels.length === 0) return true

    const frames = channels[0].length
    for (let i = 0; i < frames; i++) {
      let sum = 0
      for (let c = 0; c < channels.length; c++) sum += channels[c][i]
      this.buffer[this.filled++] = sum / channels.length
      if (this.filled === BLOCK) {
        this.port.postMessage(this.buffer, [this.buffer.buffer])
        this.buffer = new Float32Array(BLOCK)
        this.filled = 0
      }
    }
    return true
  }
}

registerProcessor('meetrec-recorder', MeetRecRecorder)
