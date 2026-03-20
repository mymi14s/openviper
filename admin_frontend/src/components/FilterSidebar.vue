<script setup lang="ts">
import { ref, computed } from 'vue'
import { useAdminStore } from '@/stores/admin'
import { formatFieldName } from '@/utils/formatters'
import type { FilterOption } from '@/types/admin'

const props = defineProps<{
  filterOptions: FilterOption[]
}>()

const emit = defineEmits<{
  (e: 'change', filters: Record<string, any>): void
}>()

const adminStore = useAdminStore()
const activeFilters = ref<Record<string, any>>({})
const debounceTimers: Record<string, ReturnType<typeof setTimeout>> = {}

const activeFilterCount = computed(() => Object.keys(activeFilters.value).length)

function applyFilter(fieldName: string, value: any) {
  if (value === undefined || value === null || value === '') {
    const copy = { ...activeFilters.value }
    delete copy[fieldName]
    activeFilters.value = copy
  } else {
    activeFilters.value = { ...activeFilters.value, [fieldName]: value }
  }
  emit('change', { ...activeFilters.value })
}

function handleChoiceFilter(fieldName: string, value: any) {
  const current = activeFilters.value[fieldName]
  if (current !== undefined && String(current) === String(value)) {
    applyFilter(fieldName, '')
  } else {
    applyFilter(fieldName, value)
  }
}

function handleTextFilter(fieldName: string, value: string) {
  clearTimeout(debounceTimers[fieldName])
  debounceTimers[fieldName] = setTimeout(() => applyFilter(fieldName, value), 300)
}

function clearAll() {
  activeFilters.value = {}
  emit('change', {} as Record<string, any>)
}
</script>

<template>
  <div class="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
    <div class="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50">
      <span class="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Filter By</span>
      <button
        v-if="activeFilterCount > 0"
        @click="clearAll"
        class="text-xs text-red-500 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300 font-medium"
      >
        Clear ({{ activeFilterCount }})
      </button>
    </div>

    <div class="p-3 space-y-4">
      <div v-for="filter in filterOptions" :key="filter.name" class="space-y-1.5">
        <p class="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
          {{ formatFieldName(filter.name) }}
        </p>

        <!-- Choice pills -->
        <div v-if="filter.choices.length > 0" class="flex flex-col gap-1">
          <button
            v-for="choice in filter.choices"
            :key="String(choice.value)"
            @click="handleChoiceFilter(filter.name, choice.value)"
            class="w-full text-left px-2.5 py-1.5 rounded text-xs transition-colors"
            :class="activeFilters[filter.name] !== undefined && String(activeFilters[filter.name]) === String(choice.value)
              ? 'bg-indigo-600 text-white font-medium'
              : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'"
          >
            {{ choice.label }}
          </button>
        </div>

        <!-- Free text -->
        <div v-else>
          <input
            type="text"
            :value="activeFilters[filter.name] ?? ''"
            @input="handleTextFilter(filter.name, ($event.target as HTMLInputElement).value)"
            placeholder="Filter..."
            class="w-full px-2.5 py-1.5 text-xs border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500"
          />
        </div>
      </div>
    </div>
  </div>
</template>
