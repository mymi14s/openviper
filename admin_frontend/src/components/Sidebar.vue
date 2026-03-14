<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, RouterLink } from 'vue-router'
import { useAdminStore } from '@/stores/admin'

const route = useRoute()
const adminStore = useAdminStore()
const searchQuery = ref('')

const modelsByApp = computed(() => {
  const grouped = { ...adminStore.modelsByApp }
  const config = adminStore.config

  // If a custom user model is active, hide the default auth.User from sidebar
  if (config.is_custom_user && grouped['auth']) {
    grouped['auth'] = grouped['auth'].filter(m => {
      const fullPath = `auth.${m.name}`
      return fullPath !== config.auth_user_model
    })
  }

  return grouped
})

const filteredModelsByApp = computed(() => {
  if (!searchQuery.value.trim()) {
    return modelsByApp.value
  }

  const query = searchQuery.value.toLowerCase()
  const filtered: Record<string, any[]> = {}

  Object.entries(modelsByApp.value).forEach(([app, models]) => {
    const filteredModels = models.filter(model =>
      model.name.toLowerCase().includes(query) ||
      model.verbose_name_plural.toLowerCase().includes(query) ||
      app.toLowerCase().includes(query)
    )
    if (filteredModels.length > 0) {
      filtered[app] = filteredModels
    }
  })

  return filtered
})

const appLabels = computed(() => {
  const labels = Object.keys(filteredModelsByApp.value).filter(
    label => filteredModelsByApp.value[label].length > 0
  )
  return labels.sort()
})

function isActiveModel(appLabel: string, modelName: string): boolean {
  return route.params.appLabel === appLabel && route.params.modelName === modelName
}

function formatAppLabel(label: string): string {
  return label.charAt(0).toUpperCase() + label.slice(1).replace(/_/g, ' ')
}

function clearSearch(): void {
  searchQuery.value = ''
}
</script>

<template>
  <aside class="w-64 bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700 flex flex-col">
    <!-- Logo -->
    <div class="flex-shrink-0 h-16 flex items-center justify-between px-4 border-b border-gray-200 dark:border-gray-700">
      <RouterLink @click="adminStore.closeSidebar" to="/dashboard" class="flex items-center gap-2">
        🐍
        <span class="text-xl font-bold text-gray-900 dark:text-white">{{ adminStore.config.admin_header_title || 'OpenViper' }}</span>
      </RouterLink>
      
      <!-- Close button (mobile only) -->
      <button 
        @click="adminStore.closeSidebar"
        class="lg:hidden p-2 text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-700 rounded-lg"
      >
        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>

    <!-- Search Section -->
    <div class="flex-shrink-0 px-4 py-3 border-b border-gray-200 dark:border-gray-700">
      <div class="relative">
        <input
          v-model="searchQuery"
          type="text"
          placeholder="Search models..."
          class="w-full px-3 py-2 pr-9 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:focus:ring-blue-400 text-sm"
        />
        <button
          v-if="searchQuery"
          @click="clearSearch"
          class="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
          title="Clear search"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
        <svg
          v-else
          class="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <circle cx="11" cy="11" r="8" stroke-width="2" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" stroke-width="2" />
        </svg>
      </div>
    </div>

    <!-- Navigation -->
    <nav class="flex-1 overflow-y-auto min-h-0">
      <div class="p-4 space-y-4">
        <!-- Dashboard link -->
        <RouterLink
          to="/dashboard"
          class="sidebar-link mb-4"
          :class="{ active: route.name === 'dashboard' }"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                  d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"/>
          </svg>
          Dashboard
        </RouterLink>

        <!-- No results message -->
        <div v-if="searchQuery && appLabels.length === 0" class="px-3 py-4 text-center">
          <p class="text-sm text-gray-500 dark:text-gray-400">No models match your search.</p>
        </div>

        <!-- Models by app -->
        <template v-for="appLabel in appLabels" :key="appLabel">
          <h3 class="px-3 mb-2 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mt-4 first:mt-0">
            {{ formatAppLabel(appLabel) }}
          </h3>
          <ul class="space-y-1 mb-4">
            <li v-for="model in filteredModelsByApp[appLabel]" :key="model.name">
              <RouterLink
                :to="`/${appLabel}/${model.name}`"
                class="sidebar-link"
                :class="{ active: isActiveModel(appLabel, model.name) }"
              >
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                        d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"/>
                </svg>
                {{ model.verbose_name_plural }}
              </RouterLink>
            </li>
          </ul>
        </template>
      </div>
    </nav>

    <!-- Footer -->
    <div class="flex-shrink-0 p-4 border-t border-gray-200 dark:border-gray-700">
      <p class="text-xs text-gray-500 dark:text-gray-400 text-center">
        {{ adminStore.config.admin_footer_title  || 'OpenViper Admin' }} - {{ new Date().getFullYear() }}
      </p>
    </div>
  </aside>
</template>

<style scoped>
aside {
  position: fixed;
  left: 0;
  top: 0;
  height: 100vh;
  width: 16rem; /* w-64 */
  overflow-y: auto;
}

@media (min-width: 1024px) {
  aside {
    position: static;
    height: 100vh;
    width: 16rem;
  }
}

aside {
  scrollbar-color: #94a3b8 transparent;
  scrollbar-width: auto;
}

aside::-webkit-scrollbar {
  width: 8px;
}

aside::-webkit-scrollbar-track {
  background: transparent;
}

aside::-webkit-scrollbar-thumb {
  background: #94a3b8;
  border-radius: 4px;
}

aside::-webkit-scrollbar-thumb:hover {
  background: #64748b;
}

@media (prefers-color-scheme: dark) {
  aside {
    scrollbar-color: #64748b transparent;
  }

  aside::-webkit-scrollbar-thumb {
    background: #64748b;
  }

  aside::-webkit-scrollbar-thumb:hover {
    background: #94a3b8;
  }
}
</style>
