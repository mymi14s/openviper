import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { User, LoginRequest } from '@/types/admin'
import { authApi } from '@/api/client'

const TOKEN_KEY = 'openviper_admin_token'
const USER_KEY = 'openviper_admin_user'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem(TOKEN_KEY))
  const user = ref<User | null>(JSON.parse(localStorage.getItem(USER_KEY) || 'null'))
  const loading = ref(false)
  const error = ref<string | null>(null)

  const isAuthenticated = computed(() => !!token.value && !!user.value)
  const isSuperuser = computed(() => user.value?.is_superuser ?? false)
  const isStaff = computed(() => user.value?.is_staff ?? false)

  async function login(credentials: LoginRequest): Promise<boolean> {
    loading.value = true
    error.value = null

    try {
      const response = await authApi.login(credentials)

      token.value = response.access_token
      user.value = response.user

      localStorage.setItem(TOKEN_KEY, response.access_token)
      localStorage.setItem(USER_KEY, JSON.stringify(response.user))

      return true
    } catch (err: any) {
      error.value = err.response?.data?.detail || err.response?.data?.error || 'Login failed'
      return false
    } finally {
      loading.value = false
    }
  }

  async function logout(): Promise<void> {
    try {
      await authApi.logout()
    } catch {
      // Ignore logout errors
    } finally {
      clearAuth()
    }
  }

  function clearAuth(): void {
    token.value = null
    user.value = null
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  }

  async function fetchCurrentUser(): Promise<void> {
    if (!token.value) return

    loading.value = true
    try {
      const fetchedUser = await authApi.getCurrentUser()
      if (!fetchedUser.is_staff && !fetchedUser.is_superuser) {
        clearAuth()
        return
      }
      user.value = fetchedUser
      localStorage.setItem(USER_KEY, JSON.stringify(user.value))
    } catch {
      clearAuth()
    } finally {
      loading.value = false
    }
  }

  async function refreshToken(): Promise<boolean> {
    if (!token.value) return false

    try {
      const response = await authApi.refreshToken()
      token.value = response.token
      localStorage.setItem(TOKEN_KEY, response.token)
      return true
    } catch {
      clearAuth()
      return false
    }
  }

  function hasPermission(_permission: string): boolean {
    if (isSuperuser.value) return true
    return isStaff.value
  }

  return {
    token,
    user,
    loading,
    error,
    isAuthenticated,
    isSuperuser,
    isStaff,
    login,
    logout,
    clearAuth,
    fetchCurrentUser,
    refreshToken,
    hasPermission,
  }
})
