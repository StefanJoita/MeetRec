/** „SPEAKER_00” → „Vorbitor 1” — aceeași etichetă ca în export și în căutare. */
export function speakerLabel(speakerId: string): string {
  const match = speakerId.match(/SPEAKER_(\d+)$/)
  return match ? `Vorbitor ${parseInt(match[1], 10) + 1}` : speakerId
}

/** Numele afișat: persoana asociată (din speakerMap), altfel „Vorbitor N”. */
export function speakerName(speakerId: string, speakerMap?: Record<string, string>): string {
  return speakerMap?.[speakerId] || speakerLabel(speakerId)
}
