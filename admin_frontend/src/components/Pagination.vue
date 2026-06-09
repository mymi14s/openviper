<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  currentPage: number
  totalPages: number
  totalItems: number
  perPage: number
  perPageOptions?: number[]
}>(), {
  perPageOptions: () => [25, 50, 100, 500, 1000],
})

const emit = defineEmits<{
  'page-change': [page: number]
  'per-page-change': [perPage: number]
}>()

const pages = computed(() => {
  const result: (number | string)[] = []
  const total = props.totalPages
  const current = props.currentPage

  if (total <= 7) {
    for (let i = 1; i <= total; i++) {
      result.push(i)
    }
  } else {
    result.push(1)

    if (current > 3) {
      result.push('...')
    }

    const start = Math.max(2, current - 1)
    const end = Math.min(total - 1, current + 1)

    for (let i = start; i <= end; i++) {
      result.push(i)
    }

    if (current < total - 2) {
      result.push('...')
    }

    result.push(total)
  }

  return result
})

const startItem = computed(() => (props.currentPage - 1) * props.perPage + 1)
const endItem = computed(() => Math.min(props.currentPage * props.perPage, props.totalItems))

function goToPage(page: number) {
  if (page >= 1 && page <= props.totalPages && page !== props.currentPage) {
    emit('page-change', page)
  }
}

function changePerPage(event: Event) {
  const target = event.target as HTMLSelectElement
  const value = Number(target.value)
  if (value !== props.perPage) {
    emit('per-page-change', value)
  }
}
</script>

<template>
  <div class="flex flex-col sm:flex-row items-center justify-between gap-3">
    <!-- Info and per-page selector -->
    <div class="flex items-center gap-3 text-sm text-gray-500 dark:text-gray-400">
      <p>
        Showing {{ startItem }} to {{ endItem }} of {{ totalItems }} results
      </p>
      <div class="flex items-center gap-1.5">
        <label for="per-page-select" class="sr-only">Items per page</label>
        <select
          id="per-page-select"
          :value="perPage"
          class="px-2 py-1 text-sm border rounded-lg bg-white dark:bg-gray-700 dark:text-gray-300 dark:border-gray-600 focus:ring-1 focus:ring-primary-500 focus:border-primary-500"
          @change="changePerPage"
        >
          <option v-for="option in perPageOptions" :key="option" :value="option">
            {{ option }} / page
          </option>
        </select>
      </div>
    </div>

    <!-- Pagination controls -->
    <nav class="flex items-center gap-1">
      <!-- Previous -->
      <button
        :disabled="currentPage === 1"
        class="p-2 rounded-lg text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
        @click="goToPage(currentPage - 1)"
      >
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/>
        </svg>
      </button>

      <!-- Page numbers -->
      <template v-for="page in pages" :key="page">
        <span v-if="page === '...'" class="px-3 py-2 text-gray-400">...</span>
        <button
          v-else
          :class="[
            'px-3 py-2 rounded-lg text-sm font-medium transition-colors',
            page === currentPage
              ? 'bg-primary-600 text-white'
              : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
          ]"
          @click="goToPage(page as number)"
        >
          {{ page }}
        </button>
      </template>

      <!-- Next -->
      <button
        :disabled="currentPage === totalPages"
        class="p-2 rounded-lg text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
        @click="goToPage(currentPage + 1)"
      >
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
        </svg>
      </button>
    </nav>
  </div>
</template>
