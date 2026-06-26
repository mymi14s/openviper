/**
 * Compare two values for equality, handling special cases like
 * File objects, arrays, and objects.
 */
export function valuesEqual(a: unknown, b: unknown): boolean {
    if (a === b) return true
    if (a == null || b == null) return a == b

    if (a instanceof File || b instanceof File) return false
    if (a instanceof Blob || b instanceof Blob) return false

    if (Array.isArray(a) && Array.isArray(b)) {
        if (a.length !== b.length) return false
        return JSON.stringify(a) === JSON.stringify(b)
    }

    if (typeof a === 'object' && typeof b === 'object') {
        return JSON.stringify(a) === JSON.stringify(b)
    }

    return a === b
}
