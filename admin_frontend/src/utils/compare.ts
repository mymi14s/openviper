/**
 * Compare two values for equality, handling special cases like
 * File objects, arrays, and objects.
 */
export function valuesEqual(a: any, b: any): boolean {
    // Handle null/undefined
    if (a === b) return true
    if (a == null || b == null) return a == b

    // File objects are always considered changed if they are present
    // (we usually can't compare content easily)
    if (a instanceof File || b instanceof File) return false
    if (a instanceof Blob || b instanceof Blob) return false

    // Arrays
    if (Array.isArray(a) && Array.isArray(b)) {
        if (a.length !== b.length) return false
        // Sort keys if they are objects? Usually not needed for simple lists
        return JSON.stringify(a) === JSON.stringify(b)
    }

    // Objects
    if (typeof a === 'object' && typeof b === 'object') {
        // Basic objects comparison via stringify
        // This handles nested structures but not circular ones
        return JSON.stringify(a) === JSON.stringify(b)
    }

    return a === b
}
