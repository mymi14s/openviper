<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from 'vue'
import { formatFieldName } from '@/utils/formatters'
import CountrySelectField from '@/components/CountrySelectField.vue'
import CurrencyFieldInput from '@/components/CurrencyField.vue'
import type { FilterOption } from '@/types/admin'

const props = defineProps<{
  filterOptions: FilterOption[]
  initialFilters?: Record<string, unknown>
}>()

const emit = defineEmits<{
  (e: 'change', filters: Record<string, unknown>): void
}>()

const activeFilters = ref<Record<string, unknown>>({ ...(props.initialFilters ?? {}) })

watch(
  () => props.initialFilters,
  (newFilters) => {
    activeFilters.value = { ...(newFilters ?? {}) }
  }
)
const debounceTimers: Record<string, ReturnType<typeof setTimeout>> = {}

onUnmounted(() => {
  for (const key of Object.keys(debounceTimers)) {
    clearTimeout(debounceTimers[key])
    delete debounceTimers[key]
  }
})

const activeFilterCount = computed(() => Object.keys(activeFilters.value).length)

function isActiveChoice(fieldName: string, choiceValue: unknown): boolean {
  return activeFilters.value[fieldName] !== undefined && String(activeFilters.value[fieldName]) === String(choiceValue)
}

function choiceClass(fieldName: string, choiceValue: unknown): string {
  return isActiveChoice(fieldName, choiceValue)
    ? 'bg-indigo-600 text-white font-medium'
    : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
}

function applyFilter(fieldName: string, value: unknown) {
  if (value === undefined || value === null || value === '') {
    const copy = { ...activeFilters.value }
    delete copy[fieldName]
    activeFilters.value = copy
  } else {
    activeFilters.value = { ...activeFilters.value, [fieldName]: value }
  }
  emit('change', { ...activeFilters.value })
}

function handleChoiceFilter(fieldName: string, value: unknown) {
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

function handlePointRadiusFilter(fieldName: string, lon: string, lat: string, radius: string) {
  if (!lon || !lat) {
    applyFilter(fieldName, '')
    return
  }
  const center = `${lon},${lat}`
  const km = radius ? parseFloat(radius) : 50
  applyFilter(fieldName, `${center},${km}km`)
}

const pointState = ref<Record<string, { lon: string; lat: string; radius: string }>>({})

function getPointState(name: string) {
  if (!pointState.value[name]) {
    pointState.value[name] = { lon: '', lat: '', radius: '' }
  }
  return pointState.value[name]
}

function onPointChange(fieldName: string) {
  const s = getPointState(fieldName)
  handlePointRadiusFilter(fieldName, s.lon, s.lat, s.radius)
}

function clearAll() {
  activeFilters.value = {}
  emit('change', {} as Record<string, unknown>)
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

        <!-- Date picker -->
        <div v-if="filter.component === 'date'" class="flex flex-col gap-1">
          <input
            type="date"
            :value="activeFilters[filter.name] ?? ''"
            @change="applyFilter(filter.name, ($event.target as HTMLInputElement).value)"
            class="w-full px-2.5 py-1.5 text-xs border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500"
          />
        </div>

        <!-- DateTime picker -->
        <div v-else-if="filter.component === 'datetime'" class="flex flex-col gap-1">
          <input
            type="datetime-local"
            :value="activeFilters[filter.name] ?? ''"
            @change="applyFilter(filter.name, ($event.target as HTMLInputElement).value)"
            class="w-full px-2.5 py-1.5 text-xs border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500"
          />
        </div>

        <!-- Point / radius filter -->
        <div v-else-if="filter.component === 'point'" class="flex flex-col gap-2">
          <div class="grid grid-cols-2 gap-1">
            <div>
              <label class="block text-xs text-gray-400 dark:text-gray-500 mb-0.5">Longitude</label>
              <input
                type="number"
                step="any"
                min="-180"
                max="180"
                v-model="getPointState(filter.name).lon"
                placeholder="e.g. −0.1276"
                class="w-full px-2 py-1.5 text-xs border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                @change="onPointChange(filter.name)"
              />
            </div>
            <div>
              <label class="block text-xs text-gray-400 dark:text-gray-500 mb-0.5">Latitude</label>
              <input
                type="number"
                step="any"
                min="-90"
                max="90"
                v-model="getPointState(filter.name).lat"
                placeholder="e.g. 51.5074"
                class="w-full px-2 py-1.5 text-xs border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                @change="onPointChange(filter.name)"
              />
            </div>
          </div>
          <div>
            <label class="block text-xs text-gray-400 dark:text-gray-500 mb-0.5">Radius (km)</label>
            <input
              type="number"
              step="1"
              min="1"
              v-model="getPointState(filter.name).radius"
              placeholder="50"
              class="w-full px-2 py-1.5 text-xs border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              @change="onPointChange(filter.name)"
            />
          </div>
          <p class="text-xs text-gray-400 dark:text-gray-500">Filter records within radius of centre point.</p>
        </div>

        <!-- Country filter (searchable dropdown) -->
        <div v-else-if="filter.component === 'country'">
          <CountrySelectField
            :modelValue="activeFilters[filter.name] ?? null"
            :choices="filter.choices"
            @update:modelValue="applyFilter(filter.name, $event ?? '')"
          />
        </div>

        <!-- Currency filter (numeric amount with currency selector) -->
        <div v-else-if="filter.component === 'currency'">
          <CurrencyFieldInput
            :model-value="(activeFilters[filter.name] as string | number | null) ?? null"
            :choices="filter.choices"
            :currency-value="(activeFilters[`${filter.name}_currency`] as string | null) ?? null"
            :allow-negative="true"
            @update:model-value="applyFilter(filter.name, $event ?? '')"
            @update:currency="applyFilter(`${filter.name}_currency`, $event ?? '')"
          />
        </div>

        <!-- Choices (Dropdown for many, pills for few) -->
        <div v-else-if="filter.choices.length > 5 || filter.component === 'select'" class="flex flex-col gap-1">
          <select
            :value="activeFilters[filter.name] ?? ''"
            @change="applyFilter(filter.name, ($event.target as HTMLSelectElement).value)"
            class="w-full px-2.5 py-1.5 text-xs border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500"
          >
            <option value="">All</option>
            <option v-for="choice in filter.choices" :key="String(choice.value)" :value="choice.value">
              {{ choice.label }}
            </option>
          </select>
        </div>

        <!-- Choice pills (for small sets) -->
        <div v-else-if="filter.choices.length > 0" class="flex flex-col gap-1">
          <button
            v-for="choice in filter.choices"
            :key="String(choice.value)"
            @click="handleChoiceFilter(filter.name, choice.value)"
            class="w-full text-left px-2.5 py-1.5 rounded text-xs transition-colors"
            :class="choiceClass(filter.name, choice.value)"
          >
            {{ choice.label }}
          </button>
        </div>

        <!-- Free text (fallback) -->
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
