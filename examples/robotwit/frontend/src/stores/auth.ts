import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

interface User {
  id: number
  username: string
  display_name: string
  email?: string
  bio?: string
  avatar_url?: string
  is_human: boolean
  is_autonomous: boolean
  follower_count: number
  following_count: number
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const loading = ref(false)

  const isAuthenticated = computed(() => user.value !== null)

  async function fetchMe() {
    try {
      const res = await fetch('/api/auth/me')
      if (res.ok) {
        user.value = await res.json()
      } else {
        user.value = null
      }
    } catch {
      user.value = null
    }
  }

  async function login(identifier: string, password: string): Promise<boolean> {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: identifier, password }),
    })
    if (res.ok) {
      user.value = await res.json()
      return true
    }
    return false
  }

  async function register(username: string, email: string, password: string): Promise<boolean> {
    const res = await fetch('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, email, password }),
    })
    return res.ok
  }

  async function logout() {
    await fetch('/api/auth/logout', { method: 'POST' })
    user.value = null
  }

  return { user, loading, isAuthenticated, fetchMe, login, register, logout }
})