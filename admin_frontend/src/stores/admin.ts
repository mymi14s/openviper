import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type {
  ModelConfig,
  ModelInstance,
  PaginatedResponse,
  DashboardStats,
  ChangeHistoryEntry,
  AdminConfig,
  FilterOption
} from '@/types/admin'
import { modelsApi, dashboardApi, historyApi } from '@/api/client'
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
  const activeFilters = ref<Record<string, any>>({})
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
    } catch (err: any) {
      error.value = err.response?.data?.error || 'Failed to fetch models'
    }
  }

  async function fetchModel(appLabel: string, modelName: string): Promise<void> {
    error.value = null
    try {
      currentModel.value = await modelsApi.getModel(appLabel, modelName)
    } catch (err: any) {
      error.value = err.response?.data?.error || 'Failed to fetch model'
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
      filters?: Record<string, any>
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
    } catch (err: any) {
      error.value = err.response?.data?.error || 'Failed to fetch instances'
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
    } catch (err: any) {
      error.value = err.response?.data?.error || 'Failed to fetch instance'
      currentInstance.value = null
      showOperationalError(error.value ?? 'Failed to fetch instance')
    }
  }

  async function createInstance(
    appLabel: string,
    modelName: string,
    data: Record<string, any>
  ): Promise<ModelInstance | null> {
    try {
      const instance = await modelsApi.createModelInstance(appLabel, modelName, data)
      return instance
    } catch (err: any) {
      // Re-throw 409 Conflict and 422 Unprocessable Entity so the caller can handle them.
      if (err.response?.status === 409 || err.response?.status === 422) {
        throw err
      }
      error.value = err.response?.data?.error || 'Failed to create instance'
      return null
    } finally {
      // Don't set loading.value = false here if we didn't set it to true
    }
  }

  async function updateInstance(
    appLabel: string,
    modelName: string,
    id: string | number,
    data: Record<string, any>
  ): Promise<ModelInstance | null> {
    try {
      const instance = await modelsApi.updateModelInstance(appLabel, modelName, id, data)
      currentInstance.value = instance
      return instance
    } catch (err: any) {
      // Re-throw 422 Unprocessable Entity so the caller can display field-level errors.
      if (err.response?.status === 422) {
        throw err
      }
      error.value = err.response?.data?.error || 'Failed to update instance'
      showOperationalError(error.value ?? 'Failed to update instance')
      return null
    } finally {
      // Don't set loading.value = false here
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
    } catch (err: any) {
      error.value = err.response?.data?.error || 'Failed to delete instance'
      showOperationalError(error.value ?? 'Failed to delete instance')
      return false
    }
  }

  async function bulkAction(
    appLabel: string,
    modelName: string,
    action: string,
    ids: Array<string | number>
  ): Promise<{ success: boolean; affected: number }> {
    error.value = null
    try {
      const result = await modelsApi.bulkAction(appLabel, modelName, { action, ids })
      if (result.success) {
        await fetchInstances(appLabel, modelName)
      }
      return result
    } catch (err: any) {
      error.value = err.response?.data?.error || 'Failed to perform bulk action'
      showOperationalError(error.value ?? 'Failed to perform bulk action')
      return { success: false, affected: 0 }
    }
  }

  async function fetchDashboard(): Promise<void> {
    error.value = null
    try {
      const data = await dashboardApi.getStats()
      dashboardStats.value = data
      recentActivity.value = data.recent_activity || []
    } catch (err: any) {
      error.value = err.response?.data?.error || 'Failed to fetch dashboard'
    }
  }

  async function fetchConfig(): Promise<void> {
    try {
      config.value = await dashboardApi.getConfig()
    } catch (err: any) {
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

  function setActiveFilter(fieldName: string, value: any): void {
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
    clearCurrent,
  }
})
