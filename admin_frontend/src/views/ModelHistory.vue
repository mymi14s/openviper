<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useAdminStore } from '@/stores/admin'
import type { ChangeHistoryEntry } from '@/types/admin'
import { formatFieldName } from '@/utils/formatters'

const props = defineProps<{
  appLabel: string
  modelName: string
  id: string
}>()

const adminStore = useAdminStore()
const history = ref<ChangeHistoryEntry[]>([])
const loading = ref(true)

const model = computed(() => adminStore.currentModel)

onMounted(async () => {
  await adminStore.fetchModel(props.appLabel, props.modelName)
  history.value = await adminStore.fetchInstanceHistory(
    props.appLabel,
    props.modelName,
    props.id
  )
  loading.value = false
})

const currentPage = ref(1)
const itemsPerPage = ref(10)

const totalPages = computed(() => Math.ceil(history.value.length / itemsPerPage.value))

const visiblePages = computed(() => {
  const pages: number[] = []
  const maxVisible = 10

  if (totalPages.value <= maxVisible) {
    for (let i = 1; i <= totalPages.value; i++) pages.push(i)
  } else {
    let start = Math.max(1, currentPage.value - Math.floor(maxVisible / 2))
    let end = start + maxVisible - 1

    if (end > totalPages.value) {
      end = totalPages.value
      start = Math.max(1, end - maxVisible + 1)
    }

    for (let i = start; i <= end; i++) pages.push(i)
  }
  return pages
})

const paginatedHistory = computed(() => {
  const start = (currentPage.value - 1) * itemsPerPage.value
  const end = start + itemsPerPage.value
  return history.value.slice(start, end)
})

function setPage(page: number) {
  if (page >= 1 && page <= totalPages.value) {
    currentPage.value = page
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr)
  return date.toLocaleString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function getActionLabel(action: string): string {
  switch (action) {
    case 'create': return 'Created'
    case 'update': return 'Updated'
    case 'delete': return 'Deleted'
    default: return action
  }
}

function getActionClass(action: string): string {
  switch (action) {
    case 'create': return 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
    case 'update': return 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400'
    case 'delete': return 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400'
    default: return 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300'
  }
}

function formatValue(value: any, fieldName?: string): string {
  if (fieldName) {
    const sensitive = ['password', 'token', 'secret', 'key', 'api_key', 'access_token', 'refresh_token']
    if (sensitive.includes(fieldName.toLowerCase()) || sensitive.some(s => fieldName.toLowerCase().includes(s))) {
      return '********'
    }
  }
  if (value === null || value === undefined) return '(empty)'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
</script>

<template>
  <div>
    <!-- Header -->
    <div class="mb-6">
      <nav class="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 mb-2">
        <RouterLink :to="`/${appLabel}/${modelName}`" class="hover:text-gray-700 dark:hover:text-gray-200">
          {{ model?.verbose_name_plural || modelName }}
        </RouterLink>
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
        </svg>
        <RouterLink :to="`/${appLabel}/${modelName}/${id}`" class="hover:text-gray-700 dark:hover:text-gray-200">
          {{ id }}
        </RouterLink>
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
        </svg>
        <span class="text-gray-900 dark:text-white">History</span>
      </nav>
      <h1 class="text-2xl font-bold text-gray-900 dark:text-white">
        Change History
      </h1>
    </div>

    <!-- Loading state -->
    <div v-if="loading" class="flex items-center justify-center py-12">
      <svg class="animate-spin w-8 h-8 text-primary-600" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
      </svg>
    </div>

    <!-- Empty state -->
    <div v-else-if="history.length === 0" class="card p-8 text-center">
      <svg class="w-12 h-12 text-gray-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
      </svg>
      <p class="text-gray-500 dark:text-gray-400">No history found for this item</p>
    </div>

    <!-- History timeline -->
    <div v-else class="space-y-4">
      <div
        v-for="entry in paginatedHistory"
        :key="entry.id"
        class="card p-6"
      >
        <div class="flex items-start justify-between mb-4">
          <div class="flex items-center gap-3">
            <span :class="['px-2 py-1 rounded text-xs font-medium', getActionClass(entry.action)]">
              {{ getActionLabel(entry.action) }}
            </span>
            <span class="text-sm text-gray-900 dark:text-white font-medium">
              {{ entry.changed_by }}
            </span>
          </div>
          <span class="text-sm text-gray-500 dark:text-gray-400">
            {{ formatDate(entry.change_time || '') }}
          </span>
        </div>

        <!-- Changes -->
        <div v-if="entry.changed_fields && Object.keys(entry.changed_fields).length > 0" class="space-y-2">
          <div
            v-for="(change, field) in entry.changed_fields"
            :key="field"
            class="flex items-start gap-4 text-sm"
          >
            <span class="font-medium text-gray-700 dark:text-gray-300 w-32 flex-shrink-0">
              {{ formatFieldName(field as string) }}
            </span>
            <div class="flex items-center gap-2 flex-1">
              <span class="text-red-600 dark:text-red-400 line-through">
                {{ formatValue(change.old, field) }}
              </span>
              <svg class="w-4 h-4 text-gray-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3"/>
              </svg>
              <span class="text-green-600 dark:text-green-400">
                {{ formatValue(change.new, field) }}
              </span>
            </div>
          </div>
        </div>

        <p v-else class="text-sm text-gray-500 dark:text-gray-400">
          No field changes recorded
        </p>
      </div>

      <!-- Pagination Controls -->
      <div v-if="totalPages > 1" class="px-4 py-3 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg flex items-center justify-between sm:px-6 mt-6">
        <div class="flex-1 flex justify-between sm:hidden">
          <button
            type="button"
            @click.prevent="setPage(currentPage - 1)"
            :disabled="currentPage === 1"
            class="relative inline-flex items-center px-4 py-2 border border-gray-300 dark:border-gray-600 text-sm font-medium rounded-md text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50"
          >
            Previous
          </button>
          <button
            type="button"
            @click.prevent="setPage(currentPage + 1)"
            :disabled="currentPage === totalPages"
            class="ml-3 relative inline-flex items-center px-4 py-2 border border-gray-300 dark:border-gray-600 text-sm font-medium rounded-md text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50"
          >
            Next
          </button>
        </div>
        <div class="hidden sm:flex-1 sm:flex sm:items-center sm:justify-between">
          <div>
            <p class="text-sm text-gray-700 dark:text-gray-300">
              Showing
              <span class="font-medium">{{ (currentPage - 1) * itemsPerPage + 1 }}</span>
              to
              <span class="font-medium">{{ Math.min(currentPage * itemsPerPage, history.length) }}</span>
              of
              <span class="font-medium">{{ history.length }}</span>
              results
            </p>
          </div>
          <div>
            <nav class="relative z-0 inline-flex rounded-md shadow-sm -space-x-px" aria-label="Pagination">
              <button
                type="button"
                @click.prevent="setPage(currentPage - 1)"
                :disabled="currentPage === 1"
                class="relative inline-flex items-center px-2 py-2 rounded-l-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-sm font-medium text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50"
              >
                <span class="sr-only">Previous</span>
                <svg class="h-5 w-5" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                  <path fill-rule="evenodd" d="M12.707 5.293a1 1 0 010 1.414L9.414 10l3.293 3.293a1 1 0 01-1.414 1.414l-4-4a1 1 0 010-1.414l4-4a1 1 0 011.414 0z" clip-rule="evenodd" />
                </svg>
              </button>

              <button
                v-for="page in visiblePages"
                :key="page"
                type="button"
                @click.prevent="setPage(page)"
                :class="[
                  page === currentPage
                    ? 'z-10 bg-primary-50 dark:bg-primary-900 border-primary-500 text-primary-600 dark:text-primary-300'
                    : 'bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-600 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700',
                  'relative inline-flex items-center px-4 py-2 border text-sm font-medium'
                ]"
              >
                {{ page }}
              </button>

              <button
                type="button"
                @click.prevent="setPage(currentPage + 1)"
                :disabled="currentPage === totalPages"
                class="relative inline-flex items-center px-2 py-2 rounded-r-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-sm font-medium text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50"
              >
                <span class="sr-only">Next</span>
                <svg class="h-5 w-5" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                  <path fill-rule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" clip-rule="evenodd" />
                </svg>
              </button>
            </nav>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
