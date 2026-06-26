import { ref, computed, type Ref } from 'vue'

/**
 * Composable for client-side pagination logic.
 * Provides page state, navigation, and computed page ranges.
 * Accepts an optional reactive source array for automatic total calculation.
 */
export function usePagination(source?: Ref<unknown[]>, options: { itemsPerPage?: number } = {}) {
  const currentPage = ref(1)
  const itemsPerPage = ref(options.itemsPerPage ?? 10)

  const totalPages = computed(() => {
    const totalItems = source ? source.value.length : 0
    return Math.ceil(totalItems / itemsPerPage.value) || 1
  })

  const visiblePages = computed(() => {
    const maxVisible = 10
    const total = totalPages.value
    const current = currentPage.value
    const pages: number[] = []

    if (total <= maxVisible) {
      for (let i = 1; i <= total; i++) pages.push(i)
    } else {
      let start = Math.max(1, current - Math.floor(maxVisible / 2))
      let end = start + maxVisible - 1

      if (end > total) {
        end = total
        start = Math.max(1, end - maxVisible + 1)
      }

      for (let i = start; i <= end; i++) pages.push(i)
    }

    return pages
  })

  const paginatedRows = computed(() => {
    if (!source) return []
    const start = (currentPage.value - 1) * itemsPerPage.value
    const end = start + itemsPerPage.value
    return source.value.slice(start, end)
  })

  function setPage(page: number) {
    if (page >= 1 && page <= totalPages.value) {
      currentPage.value = page
    }
  }

  const startItem = computed(() => (currentPage.value - 1) * itemsPerPage.value + 1)

  function endItem(totalItems: number): number {
    return Math.min(currentPage.value * itemsPerPage.value, totalItems)
  }

  return {
    currentPage,
    itemsPerPage,
    totalPages,
    visiblePages,
    setPage,
    paginatedRows,
    startItem,
    endItem,
  }
}
