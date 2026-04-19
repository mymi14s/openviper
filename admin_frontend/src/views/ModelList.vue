<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAdminStore } from '@/stores/admin'
import { modelsApi } from '@/api/client'
import DataTable from '@/components/DataTable.vue'
import Pagination from '@/components/Pagination.vue'
import FilterSidebar from '@/components/FilterSidebar.vue'
import type { FilterOption } from '@/types/admin'

const props = defineProps<{
  appLabel: string
  modelName: string
}>()

const router = useRouter()
const route = useRoute()
const adminStore = useAdminStore()

const search = ref('')
const selectedIds = ref<Array<string | number>>([])
const selectedAction = ref('')
const showBulkConfirm = ref(false)
const filterOptions = ref<FilterOption[]>([])
const activeFilters = ref<Record<string, any>>({})

function filterStorageKey(appLabel: string, modelName: string): string {
  return `openviper_filters__${appLabel}__${modelName}`
}

function sortStorageKey(appLabel: string, modelName: string): string {
  return `openviper_sort__${appLabel}__${modelName}`
}

function loadSavedFilters(appLabel: string, modelName: string): Record<string, any> {
  try {
    const raw = localStorage.getItem(filterStorageKey(appLabel, modelName))
    return raw ? (JSON.parse(raw) as Record<string, any>) : {}
  } catch {
    return {}
  }
}

function saveFilters(appLabel: string, modelName: string, filters: Record<string, any>): void {
  if (Object.keys(filters).length === 0) {
    localStorage.removeItem(filterStorageKey(appLabel, modelName))
  } else {
    localStorage.setItem(filterStorageKey(appLabel, modelName), JSON.stringify(filters))
  }
}

function loadSavedSort(appLabel: string, modelName: string): { field: string; direction: 'asc' | 'desc' } {
  try {
    const raw = localStorage.getItem(sortStorageKey(appLabel, modelName))
    return raw ? JSON.parse(raw) : { field: '', direction: 'asc' }
  } catch {
    return { field: '', direction: 'asc' }
  }
}

function saveSortState(appLabel: string, modelName: string, field: string, direction: 'asc' | 'desc'): void {
  if (!field) {
    localStorage.removeItem(sortStorageKey(appLabel, modelName))
  } else {
    localStorage.setItem(sortStorageKey(appLabel, modelName), JSON.stringify({ field, direction }))
  }
}

const model = computed(() => adminStore.currentModel)
const instances = computed(() => adminStore.instances)
const pagination = computed(() => adminStore.pagination)
const loading = ref(false)
const error = computed(() => adminStore.error)
const permissionDenied = computed(() => adminStore.permissionDenied)
const permissionMessage = computed(() => adminStore.permissionMessage)

const canAdd = computed(() => model.value?.permissions?.add ?? true)
const canChange = computed(() => model.value?.permissions?.change ?? true)
const canDelete = computed(() => model.value?.permissions?.delete ?? true)
const hasFilters = computed(() => filterOptions.value.length > 0)
const showMobileFilters = ref(false)
const sortField = ref('')
const sortDirection = ref<'asc' | 'desc'>('asc')
const activeFilterCount = computed(() => Object.values(activeFilters.value).filter(v => v !== '' && v !== null && v !== undefined).length)

async function loadFilterOptions() {
  try {
    filterOptions.value = await modelsApi.getFilterOptions(props.appLabel, props.modelName)
  } catch {
    filterOptions.value = []
  }
}

function updateUrlParams(page: number = 1): void {
  const query: Record<string, string> = {}

  if (sortField.value) {
    query.ordering = sortDirection.value === 'desc' ? `-${sortField.value}` : sortField.value
  }

  if (page > 1) {
    query.page = String(page)
  }

  if (search.value) {
    query.search = search.value
  }

  router.replace({ query })
}

function initializeFromUrl(): void {
  const urlOrdering = route.query.ordering as string | undefined
  const urlPage = route.query.page as string | undefined
  const urlSearch = route.query.search as string | undefined

  // Restore search
  if (urlSearch) {
    search.value = urlSearch
  }

  // Restore sort from URL or localStorage
  if (urlOrdering) {
    if (urlOrdering.startsWith('-')) {
      sortField.value = urlOrdering.slice(1)
      sortDirection.value = 'desc'
    } else {
      sortField.value = urlOrdering
      sortDirection.value = 'asc'
    }
  } else {
    const savedSort = loadSavedSort(props.appLabel, props.modelName)
    sortField.value = savedSort.field
    sortDirection.value = savedSort.direction
  }
}

async function loadData(page: number = 1) {
  loading.value = true
  adminStore.clearCurrent()
  try {
    await adminStore.fetchModel(props.appLabel, props.modelName)
    const ordering = sortField.value
      ? (sortDirection.value === 'desc' ? `-${sortField.value}` : sortField.value)
      : undefined
    await adminStore.fetchInstances(props.appLabel, props.modelName, {
      page,
      search: search.value || undefined,
      ordering,
      filters: Object.keys(activeFilters.value).length > 0 ? activeFilters.value : undefined,
    })
    updateUrlParams(page)
  } finally {
    loading.value = false
  }
}

function handleFilterChange(filters: Record<string, any>) {
  activeFilters.value = { ...filters }
  saveFilters(props.appLabel, props.modelName, activeFilters.value)
  loadData(1)
}

onMounted(async () => {
  activeFilters.value = loadSavedFilters(props.appLabel, props.modelName)
  initializeFromUrl()
  const urlPage = route.query.page as string | undefined
  const page = urlPage ? parseInt(urlPage, 10) : 1
  await Promise.all([loadData(page), loadFilterOptions()])
})

watch(
  () => [props.appLabel, props.modelName],
  async ([newApp, newModel]) => {
    search.value = ''
    selectedIds.value = []
    activeFilters.value = loadSavedFilters(newApp as string, newModel as string)
    initializeFromUrl()
    await Promise.all([loadData(), loadFilterOptions()])
  }
)

function handleSearch() {
  loadData(1)
}

function handleSort(field: string, direction: 'asc' | 'desc') {
  sortField.value = field
  sortDirection.value = direction
  saveSortState(props.appLabel, props.modelName, field, direction)
  loadData(1)
}

function handlePageChange(page: number) {
  loadData(page)
}

function handleRowClick(instance: any) {
  if (canChange.value) {
    router.push(`/${props.appLabel}/${props.modelName}/${instance.id}`)
  }
}

function handleSelectionChange(ids: Array<string | number>) {
  selectedIds.value = ids
}

function handleAdd() {
  router.push(`/${props.appLabel}/${props.modelName}/add`)
}

async function executeBulkAction() {
  if (!selectedAction.value || selectedIds.value.length === 0) return

  const result = await adminStore.bulkAction(
    props.appLabel,
    props.modelName,
    selectedAction.value,
    selectedIds.value
  )

  if (result.success) {
    selectedIds.value = []
    selectedAction.value = ''
  }
  showBulkConfirm.value = false
}

async function handleExport(format: 'csv' | 'json') {
  const blob = await modelsApi.exportData(
    props.appLabel,
    props.modelName,
    format,
    selectedIds.value.length > 0 ? selectedIds.value : undefined
  )
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${props.modelName}_export.${format}`
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <div class="flex flex-col lg:flex-row gap-6 items-start">

    <!-- Main content -->
    <div class="flex-1 min-w-0">
      <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-6">
        <div>
          <h1 class="text-2xl font-bold text-gray-900 dark:text-white">
            {{ model?.verbose_name_plural || modelName }}
          </h1>
          <p v-if="pagination.total > 0" class="text-sm text-gray-500 dark:text-gray-400 mt-1">
            {{ pagination.total }} {{ pagination.total === 1 ? 'item' : 'items' }}
          </p>
        </div>
        <button
          v-if="canAdd"
          @click="handleAdd"
          class="btn btn-primary flex items-center justify-center gap-2 w-full sm:w-auto"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
          </svg>
          Add {{ model?.verbose_name || modelName }}
        </button>
      </div>

      <div class="card mb-6">
        <div class="p-4 flex flex-col gap-3">
          <div class="flex items-center gap-3">
            <div class="flex-1 min-w-0">
              <div class="relative">
                <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
                </svg>
                <input
                  v-model="search"
                  type="text"
                  :placeholder="`Search ${model?.verbose_name_plural || modelName}...`"
                  class="w-full pl-10 pr-4 py-2"
                  @keyup.enter="handleSearch"
                />
              </div>
            </div>
            <button
              v-if="hasFilters"
              class="btn btn-secondary text-sm flex items-center gap-1 flex-shrink-0 lg:hidden"
              @click="showMobileFilters = !showMobileFilters"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2a1 1 0 01-.293.707L13 13.414V19a1 1 0 01-.553.894l-4 2A1 1 0 017 21v-7.586L3.293 6.707A1 1 0 013 6V4z"/>
              </svg>
              Filters
              <span v-if="activeFilterCount > 0" class="inline-flex items-center justify-center w-5 h-5 text-xs font-bold text-white bg-primary-600 rounded-full">{{ activeFilterCount }}</span>
            </button>
          </div>

          <div v-if="selectedIds.length > 0 && model?.actions?.length" class="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
            <select v-model="selectedAction" class="px-3 py-2">
              <option value="">Select action...</option>
              <option v-for="action in model.actions" :key="action" :value="action">{{ action }}</option>
            </select>
            <button :disabled="!selectedAction" class="btn btn-secondary" @click="showBulkConfirm = true">
              Apply to {{ selectedIds.length }} selected
            </button>
          </div>

          <div class="flex items-center gap-2">
            <button class="btn btn-secondary text-sm" @click="handleExport('csv')">Export CSV</button>
            <button class="btn btn-secondary text-sm" @click="handleExport('json')">Export JSON</button>
          </div>
        </div>
      </div>

      <div v-if="permissionDenied" class="mb-4 p-4 bg-yellow-50 dark:bg-yellow-900/30 border border-yellow-200 dark:border-yellow-800 rounded-lg flex items-center gap-3">
        <svg class="w-5 h-5 text-yellow-600 dark:text-yellow-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>
        </svg>
        <p class="text-sm text-yellow-700 dark:text-yellow-300">
          {{ permissionMessage || 'You do not have permission to view this data.' }}
        </p>
      </div>

      <div class="card overflow-hidden">
        <DataTable
          v-if="model"
          :model="model"
          :instances="instances"
          :loading="loading"
          :selectable="canDelete || (model.actions?.length ?? 0) > 0"
          :selected-ids="selectedIds"
          :sort-field="sortField"
          :sort-direction="sortDirection"
          @row-click="handleRowClick"
          @selection-change="handleSelectionChange"
          @sort="handleSort"
        />
      </div>

      <div v-if="pagination.totalPages > 1" class="mt-6">
        <Pagination
          :current-page="pagination.page"
          :total-pages="pagination.totalPages"
          :total-items="pagination.total"
          :per-page="pagination.perPage"
          @page-change="handlePageChange"
        />
      </div>
    </div>

    <!-- Right filter sidebar — only shown when list_filter is configured -->
    <div
      v-if="hasFilters"
      class="w-full lg:w-56 lg:flex-shrink-0 lg:sticky lg:top-6"
      :class="{ 'hidden lg:block': !showMobileFilters }"
    >
      <FilterSidebar
        :filter-options="filterOptions"
        :initial-filters="activeFilters"
        @change="handleFilterChange"
      />
    </div>

  </div>

  <Teleport to="body">
    <div v-if="showBulkConfirm" class="fixed inset-0 z-50 flex items-center justify-center">
      <div class="absolute inset-0 bg-black/50" @click="showBulkConfirm = false"></div>
      <div class="relative bg-white dark:bg-gray-800 rounded-lg shadow-xl max-w-md w-full mx-4 p-6">
        <h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-4">Confirm Action</h3>
        <p class="text-gray-600 dark:text-gray-400 mb-6">
          Are you sure you want to apply "{{ selectedAction }}" to {{ selectedIds.length }} selected items?
        </p>
        <div class="flex justify-end gap-3">
          <button class="btn btn-secondary" @click="showBulkConfirm = false">Cancel</button>
          <button class="btn btn-primary" @click="executeBulkAction">Confirm</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
