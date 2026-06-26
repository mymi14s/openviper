/**
 * Unit tests for admin store using Vitest.
 * Covers model discovery, instances, and dashboard.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useAdminStore } from '@/stores/admin'

// Mock the API client
vi.mock('@/api/client', () => ({
  modelsApi: {
    getModels: vi.fn(),
    getModel: vi.fn(),
    getModelList: vi.fn(),
    getModelInstance: vi.fn(), // Fixed from getInstance
    createModelInstance: vi.fn(), // Fixed from createInstance
    updateModelInstance: vi.fn(), // Fixed from updateInstance
    deleteModelInstance: vi.fn(), // Fixed from deleteInstance
    bulkAction: vi.fn(),
  },
  dashboardApi: {
    getStats: vi.fn(),
    getRecentActivity: vi.fn(),
  },
  historyApi: {
    getHistory: vi.fn(),
  },
}))

describe('Admin Store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  describe('Initial State', () => {
    it('initializes with default values', () => {
      const store = useAdminStore()
      expect(store.models).toEqual([])
      expect(store.currentModel).toBeNull()
      expect(store.currentInstance).toBeNull()
      expect(store.instances).toEqual([])
      expect(store.pagination.page).toBe(1)
      expect(store.loading).toBe(false)
      expect(store.error).toBeNull()
    })
  })

  describe('Computed Properties', () => {
    it('groups models by app', () => {
      const store = useAdminStore()
      store.models = [
        { app: 'blog', model_name: 'Post' } as any,
        { app: 'blog', model_name: 'Comment' } as any,
        { app: 'auth', model_name: 'User' } as any,
      ]

      expect(store.modelsByApp['blog']).toHaveLength(2)
      expect(store.modelsByApp['auth']).toHaveLength(1)
      expect(store.appLabels).toEqual(['auth', 'blog'])
    })
  })

  describe('Actions', () => {
    it('fetchModels updates models array', async () => {
      const { modelsApi } = await import('@/api/client')
      const mockModels = [{ app: 'blog', model_name: 'Post' }]
      vi.mocked(modelsApi.getModels).mockResolvedValue(mockModels as any)

      const store = useAdminStore()
      await store.fetchModels()

      expect(store.models).toEqual(mockModels)
      expect(store.loading).toBe(false)
    })

    it('fetchInstances updates instances and pagination', async () => {
      const { modelsApi } = await import('@/api/client')
      const mockResponse = {
        items: [{ id: 1, title: 'Test' }],
        total: 100,
        page: 1,
        per_page: 25,
        total_pages: 4
      }
      vi.mocked(modelsApi.getModelList).mockResolvedValue(mockResponse as any)

      const store = useAdminStore()
      await store.fetchInstances('blog', 'Post')

      expect(store.instances).toEqual(mockResponse.items)
      expect(store.pagination.total).toBe(100)
      expect(store.pagination.totalPages).toBe(4)
    })

    it('createInstance returns new instance on success', async () => {
      const { modelsApi } = await import('@/api/client')
      const mockNewInstance = { id: 10, title: 'New' }
      vi.mocked(modelsApi.createModelInstance).mockResolvedValue(mockNewInstance as any)

      const store = useAdminStore()
      const result = await store.createInstance('blog', 'Post', { title: 'New' })

      expect(result).toEqual(mockNewInstance)
      expect(modelsApi.createModelInstance).toHaveBeenCalledWith('blog', 'Post', { title: 'New' })
    })

    it('deleteInstance removes item from instances array', async () => {
      const { modelsApi } = await import('@/api/client')
      vi.mocked(modelsApi.deleteModelInstance).mockResolvedValue(undefined as any)

      const store = useAdminStore()
      store.instances = [{ id: 1 }, { id: 2 }] as any

      const success = await store.deleteInstance('blog', 'Post', 1)

      expect(success).toBe(true)
      expect(store.instances).toHaveLength(1)
      expect(store.instances[0].id).toBe(2)
    })

    it('fetchDashboard updates stats and activity', async () => {
      const { dashboardApi } = await import('@/api/client')
      const mockStats = {
        total_models: 5,
        recent_activity: [{ id: 1, action: 'add' }]
      }
      vi.mocked(dashboardApi.getStats).mockResolvedValue(mockStats as any)

      const store = useAdminStore()
      await store.fetchDashboard()

      expect(store.dashboardStats).toEqual(mockStats)
      expect(store.recentActivity).toHaveLength(1)
    })

    it('clearCurrent resets model and instance state', () => {
      const store = useAdminStore()
      store.currentModel = { app: 'blog' } as any
      store.currentInstance = { id: 1 } as any
      store.instances = [{ id: 1 }] as any

      store.clearCurrent()

      expect(store.currentModel).toBeNull()
      expect(store.currentInstance).toBeNull()
      expect(store.instances).toEqual([])
    })
  })
})
