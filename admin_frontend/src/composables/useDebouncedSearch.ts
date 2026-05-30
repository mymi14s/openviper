import { ref, onUnmounted } from 'vue'

/**
 * Composable for debounced search input.
 * Automatically cleans up pending timers on unmount.
 */
export function useDebouncedSearch(delay: number = 300) {
  const searchQuery = ref('')
  let timeout: ReturnType<typeof setTimeout> | null = null

  function debounce(callback: () => void) {
    if (timeout) clearTimeout(timeout)
    timeout = setTimeout(callback, delay)
  }

  function cancelPending() {
    if (timeout) {
      clearTimeout(timeout)
      timeout = null
    }
  }

  onUnmounted(() => {
    cancelPending()
  })

  return {
    searchQuery,
    debounce,
    cancelPending,
  }
}
