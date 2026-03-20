// src/test/Spinner.test.tsx
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { Spinner } from '@/components/ui/Spinner'

describe('Spinner', () => {
  it('randează fără erori', () => {
    const { container } = render(<Spinner />)
    expect(container.firstChild).toBeInTheDocument()
  })

  it('aplică clasa animate-spin', () => {
    const { container } = render(<Spinner />)
    expect(container.firstChild).toHaveClass('animate-spin')
  })

  it('aplică clasa implicită h-6 w-6 dacă nu e furnizată nicio clasă', () => {
    const { container } = render(<Spinner />)
    expect(container.firstChild).toHaveClass('h-6', 'w-6')
  })

  it('suprascrie dimensiunea cu className furnizat', () => {
    const { container } = render(<Spinner className="h-12 w-12" />)
    expect(container.firstChild).toHaveClass('h-12', 'w-12')
    // clasa default NU trebuie aplicată când className e furnizat
    expect(container.firstChild).not.toHaveClass('h-6')
  })

  it('păstrează clasa animate-spin indiferent de className', () => {
    const { container } = render(<Spinner className="h-4 w-4" />)
    expect(container.firstChild).toHaveClass('animate-spin')
  })
})
