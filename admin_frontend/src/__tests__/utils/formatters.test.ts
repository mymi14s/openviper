import { describe, it, expect } from 'vitest'
import { isValidUrl } from '@/utils/formatters'

describe('isValidUrl', () => {
  it('returns true for valid http URLs', () => {
    expect(isValidUrl('http://example.com')).toBe(true)
    expect(isValidUrl('http://localhost:8000')).toBe(true)
  })

  it('returns true for valid https URLs', () => {
    expect(isValidUrl('https://example.com')).toBe(true)
    expect(isValidUrl('https://google.com/search?q=test')).toBe(true)
  })

  it('returns false for invalid URLs', () => {
    expect(isValidUrl('not-a-url')).toBe(false)
    expect(isValidUrl('mailto:test@example.com')).toBe(false)
    expect(isValidUrl('ftp://example.com')).toBe(false)
    expect(isValidUrl('javascript:alert(1)')).toBe(false)
  })

  it('returns false for empty or null values', () => {
    expect(isValidUrl('')).toBe(false)
    expect(isValidUrl(null)).toBe(false)
    expect(isValidUrl(undefined)).toBe(false)
  })
})
