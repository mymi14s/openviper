<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, RouterLink } from 'vue-router'
import { useAdminStore } from '@/stores/admin'

const route = useRoute()
const adminStore = useAdminStore()

const modelsByApp = computed(() => {
  const grouped = { ...adminStore.modelsByApp }
  const config = adminStore.config

  // If a custom user model is active, hide the default auth.User from sidebar
  if (config.is_custom_user && grouped['auth']) {
    grouped['auth'] = grouped['auth'].filter(m => {
      const fullPath = `auth.${m.name}`
      return fullPath !== config.auth_user_model
    })
    
    // If auth app is now empty, we'll keep the label for now but it's cleaner
    // to filter appLabels too if needed.
  }
  
  return grouped
})

const appLabels = computed(() => {
  const labels = Object.keys(modelsByApp.value).filter(label => modelsByApp.value[label].length > 0)
  return labels.sort()
})

function isActiveModel(appLabel: string, modelName: string): boolean {
  return route.params.appLabel === appLabel && route.params.modelName === modelName
}

function formatAppLabel(label: string): string {
  return label.charAt(0).toUpperCase() + label.slice(1).replace(/_/g, ' ')
}
</script>

<template>
  <aside class="w-64 bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700 flex flex-col">
    <!-- Logo -->
    <div class="h-16 flex items-center justify-between px-4 border-b border-gray-200 dark:border-gray-700">
      <RouterLink @click="adminStore.closeSidebar" to="/dashboard" class="flex items-center gap-2">
        <svg class="w-8 h-8 text-primary-600" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
        </svg>
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

    <!-- Navigation -->
    <nav class="flex-1 overflow-y-auto p-4">
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

      <!-- Models by app -->
      <div v-for="appLabel in appLabels" :key="appLabel" class="mb-4">
        <h3 class="px-3 mb-2 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
          {{ formatAppLabel(appLabel) }}
        </h3>
        <ul class="space-y-1">
          <li v-for="model in modelsByApp[appLabel]" :key="model.name">
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
      </div>
    </nav>

    <!-- Footer -->
    <div class="p-4 border-t border-gray-200 dark:border-gray-700">
      <p class="text-xs text-gray-500 dark:text-gray-400 text-center">
        {{ adminStore.config.admin_footer_title  || 'OpenViper Admin' }} - {{ new Date().getFullYear() }}
      </p>
    </div>
  </aside>
</template>
