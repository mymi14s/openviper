import type { ModelConfig, ModelField } from '@/types/admin'

/** Validate required fields on a model form. Returns a map of field name to error message. */
export function validateRequiredFields(
  fields: ModelField[],
  formData: Record<string, unknown>
): Record<string, string> {
  const fieldErrors: Record<string, string> = {}
  for (const field of fields) {
    if (!field.required || field.readonly || field.type === 'BooleanField' || field.type === 'boolean') continue
    const val = formData[field.name]
    if (val === null || val === undefined || val === '') {
      fieldErrors[field.name] = `${field.label} is required.`
    }
  }
  return fieldErrors
}

/** Get only the fields that have changed from original data. */
export function getChangedFields(
  formData: Record<string, unknown>,
  originalData: Record<string, unknown>
): Record<string, unknown> {
  const changes: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(formData)) {
    if (key === 'id') continue
    const originalValue = originalData[key]
    if (value !== originalValue && JSON.stringify(value) !== JSON.stringify(originalValue)) {
      changes[key] = value
    }
  }
  return changes
}

/** Filter editable fields from a model config (excludes auto-generated id, created_at, updated_at). */
export function getEditableFields(model: ModelConfig): ModelField[] {
  return model.fields.filter((field) => {
    if (field.name === 'id' && field.readonly) return false
    if (field.name === 'created_at' || field.name === 'updated_at') return false
    return true
  })
}
