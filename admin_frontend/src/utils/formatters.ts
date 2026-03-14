/**
 * Converts a snake_case or camelCase string to Title Case with spaces
 * @param str - The string to format
 * @returns The formatted string
 * @example
 * formatFieldName('user_name') => 'User Name'
 * formatFieldName('created_at') => 'Created At'
 * formatFieldName('isActive') => 'Is Active'
 */
export function formatFieldName(str: string): string {
  if (!str) return ''

  // Replace underscores with spaces
  let formatted = str.replace(/_/g, ' ')

  // Insert space before capital letters (for camelCase)
  formatted = formatted.replace(/([a-z])([A-Z])/g, '$1 $2')

  // Capitalize first letter of each word
  formatted = formatted
    .split(' ')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ')

  return formatted
}

/**
 * Gets a formatted label for a field, with fallback to field name
 * @param field - Field object with optional label and name properties
 * @returns Formatted label string
 */
export function getFieldLabel(field: { label?: string; name: string }): string {
  const label = field.label || field.name
  return formatFieldName(label)
}
