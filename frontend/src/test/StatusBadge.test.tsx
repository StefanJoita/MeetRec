// src/test/StatusBadge.test.tsx
// Teste pentru componenta StatusBadge — afișează status-ul cu culori.
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { StatusBadge } from '@/components/ui/StatusBadge'

describe('StatusBadge', () => {
  it('afișează eticheta românească pentru "completed"', () => {
    render(<StatusBadge status="completed" />)
    expect(screen.getByText('Finalizat')).toBeInTheDocument()
  })

  it('afișează eticheta românească pentru "failed"', () => {
    render(<StatusBadge status="failed" />)
    expect(screen.getByText('Eșuat')).toBeInTheDocument()
  })

  it('afișează eticheta pentru "queued"', () => {
    render(<StatusBadge status="queued" />)
    expect(screen.getByText('În coadă')).toBeInTheDocument()
  })

  it('afișează eticheta pentru "transcribing"', () => {
    render(<StatusBadge status="transcribing" />)
    expect(screen.getByText('Transcriere')).toBeInTheDocument()
  })

  it('afișează eticheta pentru "uploaded"', () => {
    render(<StatusBadge status="uploaded" />)
    expect(screen.getByText('Încărcat')).toBeInTheDocument()
  })

  it('afișează eticheta pentru "archived"', () => {
    render(<StatusBadge status="archived" />)
    expect(screen.getByText('Arhivat')).toBeInTheDocument()
  })

  it('afișează eticheta pentru "pending" (status transcriere)', () => {
    render(<StatusBadge status="pending" />)
    expect(screen.getByText('În așteptare')).toBeInTheDocument()
  })

  it('afișează status-ul brut pentru valori necunoscute', () => {
    render(<StatusBadge status="unknown_status_xyz" />)
    expect(screen.getByText('unknown_status_xyz')).toBeInTheDocument()
  })

  it('randează un element <span>', () => {
    const { container } = render(<StatusBadge status="completed" />)
    expect(container.querySelector('span')).toBeInTheDocument()
  })

  it('aplică clasa verde pentru "completed"', () => {
    const { container } = render(<StatusBadge status="completed" />)
    const span = container.querySelector('span')!
    expect(span.className).toContain('green')
  })

  it('aplică clasa roșie pentru "failed"', () => {
    const { container } = render(<StatusBadge status="failed" />)
    const span = container.querySelector('span')!
    expect(span.className).toContain('red')
  })
})
