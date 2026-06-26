/** Convert a 2-letter country code to its flag emoji. */
export function countryFlag(code: string): string {
  if (!code || code.length !== 2) return ''
  const a = code.charCodeAt(0) - 65
  const b = code.charCodeAt(1) - 65
  if (a < 0 || a > 25 || b < 0 || b > 25) return ''
  return String.fromCodePoint(0x1f1e6 + a) + String.fromCodePoint(0x1f1e6 + b)
}

/** Get a CSS class for an action badge based on the action type. */
export function getActionBadgeClass(action: string): string {
  switch (action.toLowerCase()) {
    case 'create':
    case 'add':
      return 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
    case 'update':
    case 'change':
      return 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400'
    case 'delete':
      return 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
    default:
      return 'bg-gray-100 text-gray-700 dark:bg-gray-900/30 dark:text-gray-400'
  }
}

/** Format a date string for display. */
export function formatDate(dateStr: string): string {
  if (!dateStr) return 'N/A'
  return new Date(dateStr).toLocaleString()
}

/** Format a date string for short display (month + day + time). */
export function formatShortDate(dateStr: string): string {
  const date = new Date(dateStr)
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** Get an SVG path for an action icon. */
export function getActionIcon(action: string): string {
  switch (action) {
    case 'add':
      return 'M12 4v16m8-8H4'
    case 'change':
      return 'M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z'
    case 'delete':
      return 'M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16'
    default:
      return 'M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z'
  }
}
