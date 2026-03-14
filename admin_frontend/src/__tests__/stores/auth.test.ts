/**
 * Unit tests for authentication store using Vitest.
 * Covers login, logout, token management, and user state.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useAuthStore } from '@/stores/auth'

// Mock the API client and router
vi.mock('@/api/client', () => ({
  authApi: {
    login: vi.fn(),
    logout: vi.fn(),
    getCurrentUser: vi.fn(),
    refreshToken: vi.fn(), // Fixed from refresh
  },
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
  }),
  useRoute: () => ({
    path: '/',
    params: {},
  }),
}))

describe('Auth Store', () => {
  beforeEach(() => {
    // Reset Pinia state
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()

    // Explicitly mock Storage methods
    vi.spyOn(Storage.prototype, 'getItem').mockReturnValue(null)
    vi.spyOn(Storage.prototype, 'setItem')
    vi.spyOn(Storage.prototype, 'removeItem')
  })

  describe('Initial State', () => {
    it('initializes with default values', () => {
      const store = useAuthStore()
      expect(store.token).toBeNull()
      expect(store.user).toBeNull()
      expect(store.isAuthenticated).toBe(false)
      expect(store.loading).toBe(false)
      expect(store.error).toBeNull()
    })

    it('loads token from localStorage if present', async () => {
      vi.mocked(localStorage.getItem).mockImplementation((key) => {
        if (key === 'openviper_admin_token') return 'stored-token'
        if (key === 'openviper_admin_user') return JSON.stringify({ id: 1, username: 'admin' })
        return null
      })
      const store = useAuthStore()
      expect(store.token).toBe('stored-token')
      expect(store.user?.username).toBe('admin')
    })
  })

  describe('Actions', () => {
    it('login sets token and user on success', async () => {
      const { authApi } = await import('@/api/client')
      const mockUser = { id: 1, username: 'admin', is_staff: true }
      const mockResult = { access_token: 'new-token', refresh_token: 'refresh-token', user: mockUser }

      vi.mocked(authApi.login).mockResolvedValue(mockResult as any)

      const store = useAuthStore()
      const success = await store.login({ username: 'admin', password: 'password' })

      expect(success).toBe(true)
      expect(store.token).toBe('new-token')
      expect(store.user).toEqual(mockUser)
      expect(store.isAuthenticated).toBe(true)
      expect(localStorage.setItem).toHaveBeenCalledWith('openviper_admin_token', 'new-token')
      expect(localStorage.setItem).toHaveBeenCalledWith('openviper_admin_user', JSON.stringify(mockUser))
    })

    it('login handles failure and sets error message', async () => {
      const { authApi } = await import('@/api/client')
      vi.mocked(authApi.login).mockRejectedValue({
        response: { data: { detail: 'Invalid credentials' } }
      })

      const store = useAuthStore()
      const success = await store.login({ username: 'bad', password: 'bad' })

      expect(success).toBe(false)
      expect(store.token).toBeNull()
      expect(store.isAuthenticated).toBe(false)
      expect(store.error).toBe('Invalid credentials')
    })

    it('logout clears state and storage', async () => {
      const { authApi } = await import('@/api/client')
      vi.mocked(authApi.logout).mockResolvedValue(undefined)

      const store = useAuthStore()
      store.token = 'existing-token'
      store.user = { id: 1 } as any

      await store.logout()

      expect(store.token).toBeNull()
      expect(store.user).toBeNull()
      expect(store.isAuthenticated).toBe(false)
      expect(localStorage.removeItem).toHaveBeenCalledWith('openviper_admin_token')
      expect(localStorage.removeItem).toHaveBeenCalledWith('openviper_admin_user')
    })

    it('refreshToken updates token successfully', async () => {
      const { authApi } = await import('@/api/client')
      vi.mocked(authApi.refreshToken).mockResolvedValue({ token: 'refreshed-token', expires_at: '' })

      const store = useAuthStore()
      store.token = 'old-token'

      const success = await store.refreshToken()

      expect(success).toBe(true)
      expect(store.token).toBe('refreshed-token')
      expect(localStorage.setItem).toHaveBeenCalledWith('openviper_admin_token', 'refreshed-token')
    })
  })

  describe('Getters', () => {
    it('correctly identifies staff and superuser status', () => {
      const store = useAuthStore()

      store.user = { is_staff: true, is_superuser: false } as any
      expect(store.isStaff).toBe(true)
      expect(store.isSuperuser).toBe(false)

      store.user = { is_staff: true, is_superuser: true } as any
      expect(store.isStaff).toBe(true)
      expect(store.isSuperuser).toBe(true)
    })
  })
})
