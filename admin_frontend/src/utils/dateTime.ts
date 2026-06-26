import type { ModelField } from '@/types/admin'

/** Format a date/datetime value for an HTML input element. */
export function formatDateTimeValue(value: unknown, fieldType: string): string {
  if (!value) return ''

  if (fieldType === 'datetime-local' || fieldType === 'DateTimeField') {
    const date = new Date(value as string | number | Date)
    if (isNaN(date.getTime())) return ''
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    const hours = String(date.getHours()).padStart(2, '0')
    const minutes = String(date.getMinutes()).padStart(2, '0')
    return `${year}-${month}-${day}T${hours}:${minutes}`
  }

  if (fieldType === 'date' || fieldType === 'DateField') {
    const date = new Date(value as string | number | Date)
    if (isNaN(date.getTime())) return ''
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    return `${year}-${month}-${day}`
  }

  if (fieldType === 'time' || fieldType === 'TimeField') {
    const date = new Date(value as string | number | Date)
    if (isNaN(date.getTime())) return ''
    const hours = String(date.getHours()).padStart(2, '0')
    const minutes = String(date.getMinutes()).padStart(2, '0')
    return `${hours}:${minutes}`
  }

  return String(value)
}

/** Parse a datetime input value back to ISO format for the API. */
export function parseDateTimeValue(value: string, fieldType: string): string | null {
  if (!value) return null

  if (fieldType === 'datetime-local' || fieldType === 'DateTimeField') {
    const date = new Date(value)
    if (isNaN(date.getTime())) return value
    return date.toISOString()
  }

  if (fieldType === 'date' || fieldType === 'DateField') {
    return value
  }

  if (fieldType === 'time' || fieldType === 'TimeField') {
    return value
  }

  return value
}

/** Format a value for display in a textarea, handling JSON objects. */
export function formatValueForDisplay(value: unknown, field: ModelField): string {
  if (value === null || value === undefined) return ''

  if (field.type === 'JSONField') {
    if (typeof value === 'object') {
      return JSON.stringify(value, null, 2)
    }
    return String(value)
  }

  if (typeof value === 'object') {
    return JSON.stringify(value, null, 2)
  }

  return String(value)
}

/** Parse a textarea display value back to its original type. */
export function parseValueFromDisplay(value: string, field: ModelField): unknown {
  if (!value) return field.type === 'JSONField' ? null : value

  if (field.type === 'JSONField') {
    try {
      return JSON.parse(value)
    } catch {
      return value
    }
  }

  return value
}
