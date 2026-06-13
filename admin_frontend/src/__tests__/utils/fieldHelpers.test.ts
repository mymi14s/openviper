import { describe, it, expect } from 'vitest'
import { getFieldType, getFieldComponent, getInputAttributes } from '@/utils/fieldHelpers'
import type { ModelField } from '@/types/admin'

function makeField(overrides: Partial<ModelField> = {}): ModelField {
  return {
    name: 'test_field',
    type: 'CharField',
    label: 'Test Field',
    required: false,
    readonly: false,
    ...overrides,
  }
}

describe('getFieldType', () => {
  it('maps HTMLField to html', () => {
    expect(getFieldType(makeField({ type: 'HTMLField' }))).toBe('html')
  })

  it('maps TextField to textarea', () => {
    expect(getFieldType(makeField({ type: 'TextField' }))).toBe('textarea')
  })

  it('maps CharField to text', () => {
    expect(getFieldType(makeField({ type: 'CharField' }))).toBe('text')
  })

  it('falls back to text for unknown types', () => {
    expect(getFieldType(makeField({ type: 'UnknownField' }))).toBe('text')
  })
})

describe('getFieldComponent', () => {
  it('returns html for HTMLField type', () => {
    expect(getFieldComponent(makeField({ type: 'HTMLField' }))).toBe('html')
  })

  it('returns html for component=html override', () => {
    expect(getFieldComponent(makeField({ type: 'TextField', component: 'html' }))).toBe('html')
  })

  it('returns textarea for TextField type', () => {
    expect(getFieldComponent(makeField({ type: 'TextField' }))).toBe('textarea')
  })

  it('returns textarea for JSONField type', () => {
    expect(getFieldComponent(makeField({ type: 'JSONField' }))).toBe('textarea')
  })

  it('returns foreignkey when related_model is set', () => {
    expect(getFieldComponent(makeField({ type: 'CharField', related_model: 'auth/User' }))).toBe('foreignkey')
  })

  it('returns select when choices are present', () => {
    expect(getFieldComponent(makeField({ type: 'CharField', choices: [{ value: 'a', label: 'A' }] }))).toBe('select')
  })
})

describe('getInputAttributes', () => {
  it('returns empty object for HTMLField', () => {
    const attrs = getInputAttributes(makeField({ type: 'HTMLField' }))
    expect(attrs).toEqual({})
  })

  it('returns maxlength for CharField', () => {
    const attrs = getInputAttributes(makeField({ type: 'CharField', max_length: 50 }))
    expect(attrs.maxlength).toBe(50)
  })
})
