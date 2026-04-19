<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useAdminStore } from '@/stores/admin'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const adminStore = useAdminStore()

const username = ref('')
const password = ref('')
const showPassword = ref(false)

const error = ref<string | null>(null)
const loading = ref(false)

async function handleLogin() {
  error.value = null
  loading.value = true

  try {
    const success = await authStore.login({
      username: username.value,
      password: password.value,
    })

    if (success) {
      // Check for redirect in query params first, then localStorage
      let redirect = (route.query.redirect as string) || localStorage.getItem('openviper_redirect_after_login') || '/dashboard'

      // Clean up localStorage after using it
      localStorage.removeItem('openviper_redirect_after_login')

      // Ensure redirect stays within admin area
      if (!redirect.startsWith('/admin')) {
        redirect = '/dashboard'
      }

      router.push(redirect)
    } else {
      error.value = authStore.error || 'Invalid credentials'
    }
  } catch {
    error.value = 'An error occurred. Please try again.'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  document.getElementById('username')?.focus()
})
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900 px-4">
    <div class="w-full max-w-md">
      <div class="text-center mb-8">
        <div class="inline-flex items-center justify-center w-32 h-32 rounded-full bg-primary-100 mb-4 text-6xl">🐍</div>
        <h1 class="text-2xl font-bold text-gray-900 dark:text-white">{{ adminStore.config.admin_footer_title  || 'OpenViper Admin' }}</h1>
        <p class="text-gray-500 dark:text-gray-400 mt-1">Sign in to your account</p>
      </div>

      <form @submit.prevent="handleLogin" class="card p-8">
        <div
          v-if="error"
          class="mb-6 p-4 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-lg"
        >
          <p class="text-sm text-red-600 dark:text-red-400">{{ error }}</p>
        </div>

        <div class="mb-4">
          <label for="username" class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Username
          </label>
          <input
            id="username"
            v-model="username"
            type="text"
            required
            autocomplete="username"
            class="w-full px-4 py-2"
            placeholder="Enter your username"
          />
        </div>

        <div class="mb-6">
          <label for="password" class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Password
          </label>
          <div class="relative">
            <input
              id="password"
              v-model="password"
              :type="showPassword ? 'text' : 'password'"
              required
              autocomplete="current-password"
              class="w-full px-4 py-2 pr-10"
              placeholder="Enter your password"
            />
            <button
              type="button"
              class="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              @click="showPassword = !showPassword"
            >
              <svg v-if="showPassword" class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/>
              </svg>
              <svg v-else class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21"/>
              </svg>
            </button>
          </div>
        </div>

        <button
          type="submit"
          :disabled="loading"
          class="w-full btn btn-primary py-3 flex items-center justify-center gap-2"
        >
          <svg v-if="loading" class="animate-spin w-5 h-5" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
          </svg>
          <span>{{ loading ? 'Signing in...' : 'Sign in' }}</span>
        </button>
      </form>
    </div>
  </div>
</template>
