<script setup lang="ts">
import { onMounted, computed } from 'vue'
import { RouterLink } from 'vue-router'
import { useAdminStore } from '@/stores/admin'

const adminStore = useAdminStore()

const stats = computed(() => adminStore.dashboardStats)
const recentActivity = computed(() => adminStore.recentActivity)
const models = computed(() => adminStore.models)
const loading = computed(() => adminStore.loading)

onMounted(async () => {
  await Promise.all([
    adminStore.fetchDashboard(),
    adminStore.fetchModels(),
  ])
})

function formatDate(dateStr: string): string {
  const date = new Date(dateStr)
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function getActionIcon(action: string): string {
  switch (action) {
    case 'create': return 'M12 4v16m8-8H4'
    case 'update': return 'M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z'
    case 'delete': return 'M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16'
    default: return 'M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z'
  }
}

function getActionColor(action: string): string {
  switch (action) {
    case 'create': return 'text-green-500'
    case 'update': return 'text-blue-500'
    case 'delete': return 'text-red-500'
    default: return 'text-gray-500'
  }
}
</script>

<template>
  <div>
    <h1 class="text-2xl font-bold text-gray-900 dark:text-white mb-6">Dashboard</h1>

    <!-- Loading state -->
    <div v-if="loading" class="flex items-center justify-center py-12">
      <svg class="animate-spin w-8 h-8 text-primary-600" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
      </svg>
    </div>

    <template v-else>
      <!-- Stats cards -->
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <!-- Total models -->
        <div class="card p-6">
          <div class="flex items-center gap-4">
            <div class="w-12 h-12 rounded-lg bg-primary-100 dark:bg-primary-900/30 flex items-center justify-center">
              <svg class="w-6 h-6 text-primary-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"/>
              </svg>
            </div>
            <div>
              <p class="text-sm text-gray-500 dark:text-gray-400">Total Models</p>
              <p class="text-2xl font-bold text-gray-900 dark:text-white">
                {{ stats?.models_count || models.length }}
              </p>
            </div>
          </div>
        </div>

        <!-- Model counts (show first 3) -->
        <div
          v-for="(count, modelName) in stats?.stats || {}"
          :key="modelName"
          class="card p-6"
        >
          <div class="flex items-center gap-4">
            <div class="w-12 h-12 rounded-lg bg-green-100 dark:bg-green-900/30 flex items-center justify-center">
              <svg class="w-6 h-6 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/>
              </svg>
            </div>
            <div>
              <p class="text-sm text-gray-500 dark:text-gray-400 capitalize">{{ modelName }}</p>
              <p class="text-2xl font-bold text-gray-900 dark:text-white">{{ count }}</p>
            </div>
          </div>
        </div>
      </div>

      <!-- Content grid -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <!-- Quick links -->
        <div class="card">
          <div class="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
            <h2 class="text-lg font-semibold text-gray-900 dark:text-white">Quick Links</h2>
          </div>
          <div class="p-6">
            <div class="grid grid-cols-2 gap-4">
              <RouterLink
                v-for="model in models.slice(0, 6)"
                :key="`${model.app}-${model.name}`"
                :to="`/${model.app}/${model.name}`"
                class="flex items-center gap-3 p-3 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
              >
                <div class="w-10 h-10 rounded-lg bg-gray-100 dark:bg-gray-600 flex items-center justify-center">
                  <svg class="w-5 h-5 text-gray-600 dark:text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"/>
                  </svg>
                </div>
                <div>
                  <p class="text-sm font-medium text-gray-900 dark:text-white">
                    {{ model.verbose_name_plural }}
                  </p>
                  <p class="text-xs text-gray-500 dark:text-gray-400">
                    {{ model.app }}
                  </p>
                </div>
              </RouterLink>
            </div>
          </div>
        </div>

        <!-- Recent activity -->
        <div class="card">
          <div class="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
            <h2 class="text-lg font-semibold text-gray-900 dark:text-white">Recent Activity</h2>
          </div>
          <div class="divide-y divide-gray-200 dark:divide-gray-700">
            <div
              v-for="activity in recentActivity"
              :key="activity.id"
              class="px-6 py-4 flex items-start gap-4"
            >
              <div :class="['w-8 h-8 rounded-full flex items-center justify-center', getActionColor(activity.action)]">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" :d="getActionIcon(activity.action)"/>
                </svg>
              </div>
              <div class="flex-1 min-w-0">
                <p class="text-sm text-gray-900 dark:text-white">
                  <span class="font-medium">{{ activity.changed_by }}</span>
                  {{ activity.action }}d
                  <span class="font-medium">{{ activity.model_name }}</span>
                </p>
                <p class="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  {{ activity.change_time ? formatDate(activity.change_time) : '' }}
                </p>
              </div>
            </div>

            <div v-if="recentActivity.length === 0" class="px-6 py-8 text-center">
              <p class="text-gray-500 dark:text-gray-400">No recent activity</p>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
