<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'
import { useAdminStore } from '@/stores/admin'
import { searchApi } from '@/api/client'
import ChangePasswordModal from '@/components/ChangePasswordModal.vue'

const router = useRouter()
const authStore = useAuthStore()
const themeStore = useThemeStore()
const adminStore = useAdminStore()

const searchQuery = ref('')
const searchResults = ref<any[]>([])
const showSearchResults = ref(false)
const showUserMenu = ref(false)
const showPasswordModal = ref(false)
const searching = ref(false)

const user = computed(() => authStore.user)
const isDark = computed(() => themeStore.isDark)

let searchTimeout: ReturnType<typeof setTimeout> | null = null

async function handleSearch() {
  if (searchTimeout) clearTimeout(searchTimeout)

  searchTimeout = setTimeout(async () => {
    if (!searchQuery.value.trim()) {
      searchResults.value = []
      showSearchResults.value = false
      return
    }

    searching.value = true
    try {
      const response = await searchApi.globalSearch(searchQuery.value)
      // Defensive check for results presence
      searchResults.value = response?.results || []
      showSearchResults.value = searchResults.value.length > 0
    } catch (err) {
      console.error('Search error:', err)
      searchResults.value = []
    } finally {
      searching.value = false
    }
  }, 300)
}

function selectResult(result: any) {
  router.push(`/${result.app_label}/${result.model_name}/${result.id}`)
  searchQuery.value = ''
  showSearchResults.value = false
}

function toggleTheme() {
  themeStore.toggleDark()
}

async function logout() {
  await authStore.logout()
  router.push('/login')
}


function openPasswordModal() {
  showUserMenu.value = false
  showPasswordModal.value = true
}

function onPasswordChanged() {
  showPasswordModal.value = false
  // Could show a toast notification here
}
</script>

<template>
  <header class="h-16 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between px-4 md:px-6">
    <!-- Sidebar toggle (mobile only) -->
    <button
      @click="adminStore.toggleSidebar"
      class="p-2 -ml-2 mr-2 text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-700 rounded-lg lg:hidden"
    >
      <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />
      </svg>
    </button>
    <!-- Search -->
    <div class="relative flex-1 max-w-md">
      <div class="relative">
        <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
        </svg>
        <input
          v-model="searchQuery"
          type="text"
          placeholder="Search..."
          class="w-full pl-10 pr-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:ring-2 focus:ring-primary-500 focus:border-transparent"
          @input="handleSearch"
        />
        <div v-show="searching" class="absolute right-3 top-1/2 -translate-y-1/2">
          <svg class="animate-spin w-5 h-5 text-gray-400" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
          </svg>
        </div>
      </div>

      <!-- Search results dropdown -->
      <div
        v-show="showSearchResults && searchResults.length > 0"
        class="absolute top-full left-0 right-0 mt-2 bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 max-h-96 overflow-y-auto z-50"
      >
        <ul>
          <li
            v-for="result in searchResults"
            :key="`${result.app_label}-${result.model_name}-${result.id}`"
            class="px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer border-b border-gray-100 dark:border-gray-700 last:border-0"
            @mousedown="selectResult(result)"
          >
            <div class="text-sm font-medium text-gray-900 dark:text-gray-100">
              {{ result.display }}
            </div>
            <div class="text-xs text-gray-500 dark:text-gray-400">
              {{ result.app_label }} / {{ result.model_name }}
            </div>
          </li>
        </ul>
      </div>
    </div>

    <!-- Right side actions -->
    <div class="flex items-center gap-4">
      <!-- Visit Site Link -->
      <a
        href="/"
        target="_blank"
        rel="noopener noreferrer"
        class="px-3 py-2 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors text-sm font-medium flex items-center gap-2"
        title="Visit the site"
      >
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/>
        </svg>
        <span class="hidden sm:inline">Visit Site</span>
      </a>

      <!-- Theme toggle -->
      <button
        @click="toggleTheme"
        data-testid="theme-toggle"
        class="p-2 rounded-lg text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-700 transition-colors"
        :title="isDark ? 'Switch to light mode' : 'Switch to dark mode'"
      >
        <svg v-if="isDark" class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"/>
        </svg>
        <svg v-else class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"/>
        </svg>
      </button>

      <!-- User menu -->
      <div class="relative">
        <button
          @click="showUserMenu = !showUserMenu"
          data-testid="user-menu"
          class="flex items-center gap-2 p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
        >
          <div class="w-8 h-8 rounded-full bg-primary-600 flex items-center justify-center text-white font-medium">
            {{ user?.username?.charAt(0).toUpperCase() || 'U' }}
          </div>
          <span class="hidden sm:inline text-sm font-medium text-gray-700 dark:text-gray-300">
            {{ user?.username || 'User' }}
          </span>
          <svg class="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
          </svg>
        </button>

        <!-- Dropdown menu -->
        <div
          v-if="showUserMenu"
          class="absolute right-0 mt-2 w-48 bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 py-1 z-50"
        >
          <div class="px-4 py-2 border-b border-gray-200 dark:border-gray-700">
            <p class="text-sm font-medium text-gray-900 dark:text-gray-100">{{ user?.username }}</p>
            <p class="text-xs text-gray-500 dark:text-gray-400">{{ user?.email }}</p>
          </div>
          <button
            @click="openPasswordModal"
            class="w-full px-4 py-2 text-left text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          >
            Change Password
          </button>
          <button
            @click="logout"
            data-testid="logout-button"
            class="w-full px-4 py-2 text-left text-sm text-red-600 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          >
            Logout
          </button>
        </div>
      </div>
    </div>

    <!-- Change Password Modal -->
    <ChangePasswordModal
      :show="showPasswordModal"
      @close="showPasswordModal = false"
      @success="onPasswordChanged"
    />
  </header>
</template>
