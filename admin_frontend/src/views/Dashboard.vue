<script setup lang="ts">
import { onMounted, computed, ref } from 'vue'
import { Bar, Doughnut } from 'vue-chartjs'
import {
  Chart as ChartJS,
  Title,
  Tooltip,
  Legend,
  BarElement,
  CategoryScale,
  LinearScale,
  ArcElement,
} from 'chart.js'
import { useAdminStore } from '@/stores/admin'

ChartJS.register(Title, Tooltip, Legend, BarElement, CategoryScale, LinearScale, ArcElement)

const adminStore = useAdminStore()

const recentActivity = computed(() => adminStore.recentActivity)
const loading = ref(false)

onMounted(async () => {
  loading.value = true
  try {
    await Promise.all([
      adminStore.fetchDashboard(),
    ])

  } finally {
    loading.value = false
  }
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
    case 'add': return 'M12 4v16m8-8H4'
    case 'change': return 'M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z'
    case 'delete': return 'M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16'
    default: return 'M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z'
  }
}

function getActionBadgeClass(action: string): string {
  switch (action) {
    case 'add': return 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
    case 'change': return 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400'
    case 'delete': return 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
    default: return 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300'
  }
}

const activityBreakdown = computed(() => {
  const counts: Record<string, number> = { add: 0, change: 0, delete: 0 }
  for (const entry of recentActivity.value) {
    if (entry.action in counts) counts[entry.action]++
  }
  return counts
})

const totalActivity = computed(() =>
  Object.values(activityBreakdown.value).reduce((a, b) => a + b, 0)
)

const last7Days = computed(() => {
  const days: string[] = []
  for (let i = 6; i >= 0; i--) {
    const d = new Date()
    d.setDate(d.getDate() - i)
    days.push(d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }))
  }
  return days
})

const activityByDay = computed(() => {
  const counts: Record<string, number> = {}
  for (const label of last7Days.value) counts[label] = 0
  for (const entry of recentActivity.value) {
    if (!entry.change_time) continue
    const label = new Date(entry.change_time).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
    })
    if (label in counts) counts[label]++
  }
  return Object.values(counts)
})

const barChartData = computed(() => ({
  labels: last7Days.value,
  datasets: [
    {
      label: 'Activity',
      data: activityByDay.value,
      backgroundColor: 'rgba(99,102,241,0.7)',
      borderColor: 'rgba(99,102,241,1)',
      borderWidth: 1,
      borderRadius: 4,
    },
  ],
}))

const barChartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: { legend: { display: false } },
  scales: {
    y: {
      beginAtZero: true,
      ticks: { stepSize: 1, color: '#9ca3af' },
      grid: { color: 'rgba(156,163,175,0.15)' },
    },
    x: { ticks: { color: '#9ca3af' }, grid: { display: false } },
  },
}

const doughnutData = computed(() => ({
  labels: ['Added', 'Changed', 'Deleted'],
  datasets: [
    {
      data: [
        activityBreakdown.value.add,
        activityBreakdown.value.change,
        activityBreakdown.value.delete,
      ],
      backgroundColor: [
        'rgba(34,197,94,0.8)',
        'rgba(59,130,246,0.8)',
        'rgba(239,68,68,0.8)',
      ],
      borderColor: ['#16a34a', '#2563eb', '#dc2626'],
      borderWidth: 1,
    },
  ],
}))

const doughnutOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      position: 'bottom' as const,
      labels: { color: '#9ca3af', padding: 16, font: { size: 12 } },
    },
  },
}

</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-2xl font-bold text-gray-900 dark:text-white">Reports &amp; Statistics</h1>
      <span class="text-sm text-gray-500 dark:text-gray-400">Last 7 days of activity</span>
    </div>

    <!-- Loading state -->
    <div v-if="loading" class="flex items-center justify-center py-12">
      <svg class="animate-spin w-8 h-8 text-primary-600" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
      </svg>
    </div>

    <template v-else>

      <!-- Charts row -->
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">

        <!-- Activity over last 7 days — bar chart -->
        <div class="card lg:col-span-2">
          <div class="px-6 py-4 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
            <h2 class="text-base font-semibold text-gray-900 dark:text-white">Activity – Last 7 Days</h2>
            <span class="text-2xl font-bold text-indigo-600">{{ totalActivity }}</span>
          </div>
          <div class="p-6" style="height: 240px">
            <Bar :data="barChartData" :options="barChartOptions" />
          </div>
        </div>

        <!-- Action breakdown — doughnut chart -->
        <div class="card">
          <div class="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
            <h2 class="text-base font-semibold text-gray-900 dark:text-white">Action Breakdown</h2>
          </div>
          <div class="p-6" style="height: 240px">
            <Doughnut :data="doughnutData" :options="doughnutOptions" />
          </div>
        </div>
      </div>

      <!-- Bottom row: action summary chips + recent activity -->
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">

        <!-- Action summary chips -->
        <div class="card p-6 flex flex-col gap-4">
          <h2 class="text-base font-semibold text-gray-900 dark:text-white mb-1">Summary</h2>

          <div class="flex items-center justify-between p-3 rounded-lg bg-green-50 dark:bg-green-900/20">
            <div class="flex items-center gap-2">
              <div class="w-7 h-7 rounded-full bg-green-100 dark:bg-green-900/40 flex items-center justify-center">
                <svg class="w-3.5 h-3.5 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
                </svg>
              </div>
              <span class="text-sm font-medium text-green-700 dark:text-green-400">Added</span>
            </div>
            <span class="text-xl font-bold text-green-700 dark:text-green-400">{{ activityBreakdown.add }}</span>
          </div>

          <div class="flex items-center justify-between p-3 rounded-lg bg-blue-50 dark:bg-blue-900/20">
            <div class="flex items-center gap-2">
              <div class="w-7 h-7 rounded-full bg-blue-100 dark:bg-blue-900/40 flex items-center justify-center">
                <svg class="w-3.5 h-3.5 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/>
                </svg>
              </div>
              <span class="text-sm font-medium text-blue-700 dark:text-blue-400">Changed</span>
            </div>
            <span class="text-xl font-bold text-blue-700 dark:text-blue-400">{{ activityBreakdown.change }}</span>
          </div>

          <div class="flex items-center justify-between p-3 rounded-lg bg-red-50 dark:bg-red-900/20">
            <div class="flex items-center gap-2">
              <div class="w-7 h-7 rounded-full bg-red-100 dark:bg-red-900/40 flex items-center justify-center">
                <svg class="w-3.5 h-3.5 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                </svg>
              </div>
              <span class="text-sm font-medium text-red-700 dark:text-red-400">Deleted</span>
            </div>
            <span class="text-xl font-bold text-red-700 dark:text-red-400">{{ activityBreakdown.delete }}</span>
          </div>
        </div>

        <!-- Recent activity feed -->
        <div class="card lg:col-span-2">
          <div class="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
            <h2 class="text-base font-semibold text-gray-900 dark:text-white">Recent Activity</h2>
          </div>
          <div class="divide-y divide-gray-100 dark:divide-gray-700/60 max-h-80 overflow-y-auto">
            <div
              v-for="activity in recentActivity"
              :key="activity.id"
              class="px-6 py-3 flex items-center gap-3"
            >
              <svg class="w-4 h-4 text-gray-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" :d="getActionIcon(activity.action)"/>
              </svg>
              <div class="flex-1 min-w-0">
                <p class="text-sm text-gray-800 dark:text-gray-200 truncate">
                  <span class="font-medium">{{ activity.changed_by || 'System' }}</span>
                  &nbsp;·&nbsp;
                  <span class="capitalize font-medium">{{ activity.model_name }}</span>
                  <span v-if="activity.object_repr" class="text-gray-500 dark:text-gray-400"> — {{ activity.object_repr }}</span>
                </p>
              </div>
              <div class="flex items-center gap-2 flex-shrink-0">
                <span :class="['text-xs font-medium px-2 py-0.5 rounded-full capitalize', getActionBadgeClass(activity.action)]">
                  {{ activity.action }}
                </span>
                <span class="text-xs text-gray-400 hidden sm:block">
                  {{ activity.change_time ? formatDate(activity.change_time) : '' }}
                </span>
              </div>
            </div>

            <div v-if="recentActivity.length === 0" class="px-6 py-10 text-center">
              <svg class="w-8 h-8 text-gray-300 dark:text-gray-600 mx-auto mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
              </svg>
              <p class="text-sm text-gray-500 dark:text-gray-400">No recent activity</p>
            </div>
          </div>
        </div>

      </div>
    </template>
  </div>
</template>
