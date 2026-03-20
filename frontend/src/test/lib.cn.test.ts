// src/test/lib.cn.test.ts
// Teste pentru utilitarul cn() — combinator de clase CSS.
import { describe, it, expect } from 'vitest'
import { cn } from '@/lib/cn'

describe('cn()', () => {
  it('returnează un string gol fără argumente', () => {
    expect(cn()).toBe('')
  })

  it('returnează o singură clasă', () => {
    expect(cn('foo')).toBe('foo')
  })

  it('combină mai multe clase', () => {
    expect(cn('foo', 'bar', 'baz')).toBe('foo bar baz')
  })

  it('ignoră valori falsy (undefined, false, null)', () => {
    expect(cn('foo', undefined, false, null, 'bar')).toBe('foo bar')
  })

  it('acceptă obiecte condiționale', () => {
    expect(cn({ active: true, hidden: false })).toBe('active')
  })

  it('combină string-uri și obiecte', () => {
    expect(cn('base', { extra: true, skip: false })).toBe('base extra')
  })
})
