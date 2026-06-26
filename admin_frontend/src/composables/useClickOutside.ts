import { onMounted, onUnmounted, type Ref } from 'vue'

/**
 * Composable for detecting clicks outside a container element.
 * Automatically registers and cleans up event listeners.
 */
export function useClickOutside(container: Ref<HTMLElement | null>, callback: (event: MouseEvent) => void) {
  function handleClickOutside(event: MouseEvent) {
    if (container.value && !container.value.contains(event.target as Node)) {
      callback(event)
    }
  }

  onMounted(() => {
    document.addEventListener('mousedown', handleClickOutside)
  })

  onUnmounted(() => {
    document.removeEventListener('mousedown', handleClickOutside)
  })
}
