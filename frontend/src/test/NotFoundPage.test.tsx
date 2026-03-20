// src/test/NotFoundPage.test.tsx
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import NotFoundPage from '@/pages/NotFoundPage'

function renderPage() {
  return render(
    <MemoryRouter>
      <NotFoundPage />
    </MemoryRouter>
  )
}

describe('NotFoundPage', () => {
  it('afișează codul 404', () => {
    renderPage()
    expect(screen.getByText('404')).toBeInTheDocument()
  })

  it('afișează un mesaj de eroare', () => {
    renderPage()
    // Textul exact poate varia, verificăm că există ceva descriptiv
    const body = document.body.textContent ?? ''
    expect(body.toLowerCase()).toMatch(/găsit|not found|pagina|inexist/i)
  })

  it('conține un link de navigare înapoi', () => {
    renderPage()
    const link = screen.getByRole('link')
    expect(link).toBeInTheDocument()
  })
})
