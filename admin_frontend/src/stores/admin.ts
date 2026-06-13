import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type {
  ModelConfig,
  ModelInstance,
  PaginatedResponse,
  DashboardStats,
  ChangeHistoryEntry,
  AdminConfig,
  FilterOption,
  BulkActionResult,
  ExportFormat
} from '@/types/admin'
import { modelsApi, dashboardApi, historyApi, searchApi } from '@/api/client'
import { useAlertsStore } from '@/stores/alerts'

export const useAdminStore = defineStore('admin', () => {
  const models = ref<ModelConfig[]>([])
  const currentModel = ref<ModelConfig | null>(null)
  const currentInstance = ref<ModelInstance | null>(null)
  const instances = ref<ModelInstance[]>([])
  const permissionDenied = ref(false)
  const permissionMessage = ref<string | null>(null)
  const pagination = ref({
    page: 1,
    perPage: 25,
    total: 0,
    totalPages: 0,
  })
  const dashboardStats = ref<DashboardStats | null>(null)
  const recentActivity = ref<ChangeHistoryEntry[]>([])
  const config = ref<AdminConfig>({
    admin_title: 'OpenViper Admin',
    admin_header_title: 'OpenViper',
    admin_footer_title: 'OpenViper Admin'
  })
  const loading = ref(false)
  const error = ref<string | null>(null)
  const filterOptions = ref<FilterOption[]>([])
  const activeFilters = ref<Record<string, unknown>>({})
  const filterSidebarOpen = ref(false)
  const filterLoading = ref(false)

  const modelsByApp = computed(() => {
    const grouped: Record<string, ModelConfig[]> = {}
    for (const model of models.value) {
      if (!grouped[model.app]) {
        grouped[model.app] = []
      }
      grouped[model.app].push(model)
    }
    return grouped
  })

  const appLabels = computed(() => Object.keys(modelsByApp.value).sort())

  function showOperationalError(message: string): void {
    const alertsStore = useAlertsStore()
    alertsStore.show({ type: 'error', title: 'Operation Failed', message })
  }

  async function fetchModels(): Promise<void> {
    error.value = null
    try {
      models.value = await modelsApi.getModels()
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { error?: string } } }
      error.value = axiosErr.response?.data?.error || 'Failed to fetch models'
    }
  }

  async function fetchModel(appLabel: string, modelName: string): Promise<void> {
    error.value = null
    try {
      currentModel.value = await modelsApi.getModel(appLabel, modelName)
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { error?: string } } }
      error.value = axiosErr.response?.data?.error || 'Failed to fetch model'
      currentModel.value = null
    }
  }

  async function fetchInstances(
    appLabel: string,
    modelName: string,
    params: {
      page?: number
      perPage?: number
      search?: string
      ordering?: string
      filters?: Record<string, unknown>
    } = {}
  ): Promise<void> {
    error.value = null
    permissionDenied.value = false
    permissionMessage.value = null
    try {
      const response: PaginatedResponse<ModelInstance> = await modelsApi.getModelList(
        appLabel,
        modelName,
        {
          page: params.page || pagination.value.page,
          per_page: params.perPage || pagination.value.perPage,
          search: params.search,
          ordering: params.ordering,
          filters: params.filters,
        }
      )
      instances.value = response.items
      pagination.value = {
        page: response.page,
        perPage: response.per_page,
        total: response.total,
        totalPages: response.total_pages,
      }
      if (response.permission_denied) {
        permissionDenied.value = true
        permissionMessage.value = response.permission_message ?? null
      }
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { error?: string } } }
      error.value = axiosErr.response?.data?.error || 'Failed to fetch instances'
      instances.value = []
      showOperationalError(error.value ?? 'Failed to fetch instances')
    }
  }

  async function fetchInstance(
    appLabel: string,
    modelName: string,
    id: string | number
  ): Promise<void> {
    error.value = null
    try {
      currentInstance.value = await modelsApi.getModelInstance(appLabel, modelName, id)
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { error?: string } } }
      error.value = axiosErr.response?.data?.error || 'Failed to fetch instance'
      currentInstance.value = null
      showOperationalError(error.value ?? 'Failed to fetch instance')
    }
  }

  async function createInstance(
    appLabel: string,
    modelName: string,
    data: Record<string, unknown>
  ): Promise<ModelInstance | null> {
    try {
      const instance = await modelsApi.createModelInstance(appLabel, modelName, data)
      return instance
    } catch (err: unknown) {
      const axiosErr = err as { response?: { status?: number; data?: { error?: string } } }
      if (axiosErr.response?.status === 409 || axiosErr.response?.status === 422) {
        throw err
      }
      error.value = axiosErr.response?.data?.error || 'Failed to create instance'
      return null
    }
  }

  async function updateInstance(
    appLabel: string,
    modelName: string,
    id: string | number,
    data: Record<string, unknown>
  ): Promise<ModelInstance | null> {
    try {
      const instance = await modelsApi.updateModelInstance(appLabel, modelName, id, data)
      currentInstance.value = instance
      return instance
    } catch (err: unknown) {
      const axiosErr = err as { response?: { status?: number; data?: { error?: string } } }
      if (axiosErr.response?.status === 422) {
        throw err
      }
      error.value = axiosErr.response?.data?.error || 'Failed to update instance'
      showOperationalError(error.value ?? 'Failed to update instance')
      return null
    }
  }

  async function deleteInstance(
    appLabel: string,
    modelName: string,
    id: string | number
  ): Promise<boolean> {
    error.value = null
    try {
      await modelsApi.deleteModelInstance(appLabel, modelName, id)
      instances.value = instances.value.filter((i) => i.id !== id)
      if (currentInstance.value?.id === id) {
        currentInstance.value = null
      }
      return true
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { error?: string } } }
      error.value = axiosErr.response?.data?.error || 'Failed to delete instance'
      showOperationalError(error.value ?? 'Failed to delete instance')
      return false
    }
  }

  async function bulkAction(
    appLabel: string,
    modelName: string,
    action: string,
    ids: Array<string | number>
  ): Promise<BulkActionResult> {
    error.value = null
    try {
      const result = await modelsApi.bulkAction(appLabel, modelName, { action, ids })
      if (result.success) {
        await fetchInstances(appLabel, modelName)
      }
      return result
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { error?: string } } }
      error.value = axiosErr.response?.data?.error || 'Failed to perform bulk action'
      showOperationalError(error.value ?? 'Failed to perform bulk action')
      return { success: false, count: 0, message: error.value, errors: null }
    }
  }

  async function fetchDashboard(): Promise<void> {
    error.value = null
    try {
      const data = await dashboardApi.getStats()
      dashboardStats.value = data
      recentActivity.value = data.recent_activity || []
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { error?: string } } }
      error.value = axiosErr.response?.data?.error || 'Failed to fetch dashboard'
    }
  }

  async function fetchConfig(): Promise<void> {
    try {
      config.value = await dashboardApi.getConfig()
    } catch (err: unknown) {
      console.error('Failed to fetch admin config:', err)
    }
  }

  async function fetchRecentActivity(limit: number = 10): Promise<void> {
    try {
      recentActivity.value = await dashboardApi.getRecentActivity(limit)
    } catch {
      recentActivity.value = []
    }
  }

  async function fetchInstanceHistory(
    appLabel: string,
    modelName: string,
    id: string | number
  ): Promise<ChangeHistoryEntry[]> {
    try {
      return await historyApi.getHistory(appLabel, modelName, id)
    } catch {
      return []
    }
  }

  async function globalSearch(query: string): Promise<Array<{
    app_label: string
    model_name: string
    id: string | number
    display: string
    score: number
  }>> {
    try {
      const response = await searchApi.globalSearch(query)
      return response.results ?? []
    } catch {
      return []
    }
  }

  async function fetchSingleInstance(
    appLabel: string,
    modelName: string
  ): Promise<void> {
    error.value = null
    try {
      currentInstance.value = await modelsApi.getSingleInstance(appLabel, modelName)
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { error?: string } } }
      error.value = axiosErr.response?.data?.error || 'Failed to fetch instance'
      currentInstance.value = null
      showOperationalError(error.value ?? 'Failed to fetch instance')
    }
  }

  async function updateSingleInstance(
    appLabel: string,
    modelName: string,
    data: Record<string, unknown>
  ): Promise<ModelInstance | null> {
    try {
      const instance = await modelsApi.updateSingleInstance(appLabel, modelName, data)
      currentInstance.value = instance
      return instance
    } catch (err: unknown) {
      const axiosErr = err as { response?: { status?: number; data?: { error?: string } } }
      if (axiosErr.response?.status === 422) {
        throw err
      }
      error.value = axiosErr.response?.data?.error || 'Failed to update instance'
      showOperationalError(error.value ?? 'Failed to update instance')
      return null
    }
  }

  async function fetchFilterOptions(appLabel: string, modelName: string): Promise<void> {
    filterLoading.value = true
    try {
      filterOptions.value = await modelsApi.getFilterOptions(appLabel, modelName)
    } catch {
      filterOptions.value = []
    } finally {
      filterLoading.value = false
    }
  }

  function setActiveFilter(fieldName: string, value: unknown): void {
    if (value === undefined || value === null || value === '') {
      const updated = { ...activeFilters.value }
      delete updated[fieldName]
      activeFilters.value = updated
    } else {
      activeFilters.value = { ...activeFilters.value, [fieldName]: value }
    }
  }

  function clearAllFilters(): void {
    activeFilters.value = {}
  }

  function setPerPage(perPage: number): void {
    pagination.value = { ...pagination.value, perPage }
  }

  function toggleFilterSidebar(): void {
    filterSidebarOpen.value = !filterSidebarOpen.value
  }

  function closeFilterSidebar(): void {
    filterSidebarOpen.value = false
  }

  const isSidebarOpen = ref(false)

  function toggleSidebar(): void {
    isSidebarOpen.value = !isSidebarOpen.value
  }

  function closeSidebar(): void {
    isSidebarOpen.value = false
  }

  async function clearCache(): Promise<void> {
    loading.value = true
    try {
      // Re-fetch essential data
      await Promise.all([
        fetchModels(),
        fetchConfig(),
        fetchDashboard()
      ])
    } finally {
      loading.value = false
    }
  }

  function clearCurrent(): void {
    currentModel.value = null
    currentInstance.value = null
    instances.value = []
  }

  async function searchForeignKey(
    appLabel: string,
    modelName: string,
    query: string,
    limit: number = 20
  ): Promise<Array<{ value: string | number | boolean; label: string }>> {
    return modelsApi.searchForeignKey(appLabel, modelName, query, limit)
  }

  async function getForeignKeyModel(appLabel: string, modelName: string): Promise<ModelConfig> {
    return modelsApi.getModel(appLabel, modelName)
  }

  async function getForeignKeyModelInstance(
    appLabel: string,
    modelName: string,
    id: string | number
  ): Promise<ModelInstance> {
    return modelsApi.getModelInstance(appLabel, modelName, id)
  }

  async function createForeignKeyInstance(
    appLabel: string,
    modelName: string,
    data: Record<string, unknown>
  ): Promise<ModelInstance> {
    return modelsApi.createModelInstance(appLabel, modelName, data)
  }

  async function exportData(
    appLabel: string,
    modelName: string,
    format: ExportFormat,
    params: { ids?: Array<string | number> } = {}
  ): Promise<Blob> {
    return modelsApi.exportData(appLabel, modelName, format, params.ids)
  }

  return {
    isSidebarOpen,
    toggleSidebar,
    closeSidebar,
    filterOptions,
    activeFilters,
    filterSidebarOpen,
    filterLoading,
    fetchFilterOptions,
    setActiveFilter,
    clearAllFilters,
    setPerPage,
    toggleFilterSidebar,
    closeFilterSidebar,
    clearCache,
    models,
    currentModel,
    currentInstance,
    instances,
    permissionDenied,
    permissionMessage,
    pagination,
    dashboardStats,
    recentActivity,
    config,
    loading,
    error,
    modelsByApp,
    appLabels,
    fetchModels,
    fetchModel,
    fetchInstances,
    fetchInstance,
    createInstance,
    updateInstance,
    deleteInstance,
    bulkAction,
    fetchDashboard,
    fetchConfig,
    fetchRecentActivity,
    fetchInstanceHistory,
    globalSearch,
    fetchSingleInstance,
    updateSingleInstance,
    clearCurrent,
    searchForeignKey,
    getForeignKeyModel,
    getForeignKeyModelInstance,
    createForeignKeyInstance,
    exportData,
  }
})
