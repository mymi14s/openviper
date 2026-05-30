<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import type { ModelInstance, ModelConfig, ChangeHistoryEntry } from '@/types/admin'
import { useAdminStore } from '@/stores/admin'
import { formatDate, getActionBadgeClass } from '@/utils/display'

const props = defineProps<{
  appLabel: string
  modelName: string
  instance: ModelInstance
  model: ModelConfig
}>()

const adminStore = useAdminStore()
const history = ref<ChangeHistoryEntry[]>([])
const loadingHistory = ref(false)

async function fetchHistory() {
  if (!props.instance?.id) return

  loadingHistory.value = true
  try {
    const data = await adminStore.fetchInstanceHistory(
      props.appLabel,
      props.modelName,
      props.instance.id
    )
    history.value = data.slice(0, 5)
  } catch (err) {
    console.error('Failed to fetch history:', err)
  } finally {
    loadingHistory.value = false
  }
}

onMounted(fetchHistory)

watch(() => props.instance?.id, fetchHistory)

defineExpose({ fetchHistory })
</script>

<template>
  <div class="space-y-6">
    <!-- Metadata Card -->
    <div class="card p-5">
      <h3 class="text-sm font-semibold text-gray-900 dark:text-white uppercase tracking-wider mb-4 flex items-center gap-2">
        <svg class="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        Quick Info
      </h3>
      <div class="space-y-3">
        <div>
          <label class="text-xs text-gray-500 dark:text-gray-400 block mb-1">Internal ID</label>
          <code class="text-sm font-mono text-gray-900 dark:text-gray-200 bg-gray-100 dark:bg-gray-700 px-1.5 py-0.5 rounded">
            {{ instance.id }}
          </code>
        </div>
        <div v-if="instance.created_at || instance.created">
          <label class="text-xs text-gray-500 dark:text-gray-400 block mb-1">Created</label>
          <span class="text-sm text-gray-900 dark:text-gray-200">
            {{ formatDate(instance.created_at || instance.created) }}
          </span>
        </div>
        <div v-if="instance.updated_at || instance.updated">
          <label class="text-xs text-gray-500 dark:text-gray-400 block mb-1">Last Updated</label>
          <span class="text-sm text-gray-900 dark:text-gray-200">
            {{ formatDate(instance.updated_at || instance.updated) }}
          </span>
        </div>
        <div>
          <label class="text-xs text-gray-500 dark:text-gray-400 block mb-1">Model</label>
          <span class="text-sm text-gray-900 dark:text-gray-200 italic">
            {{ model.verbose_name }}
          </span>
        </div>
      </div>
    </div>

    <!-- Recent Activity Card -->
    <div class="card p-5">
      <h3 class="text-sm font-semibold text-gray-900 dark:text-white uppercase tracking-wider mb-4 flex items-center justify-between">
        <span class="flex items-center gap-2">
          <svg class="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          Audit Log
        </span>
        <button v-if="history.length > 0" @click="$emit('goToHistory')" class="text-xs text-primary-600 hover:text-primary-700 font-medium">View All</button>
      </h3>

      <div v-if="loadingHistory" class="flex justify-center py-4">
        <svg class="animate-spin h-5 w-5 text-gray-400" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
      </div>

      <div v-else-if="history.length === 0" class="text-center py-4 text-sm text-gray-500 italic">
        No recent changes
      </div>

      <div v-else class="relative">
        <!-- Timeline Line -->
        <div class="absolute left-2.5 top-0 bottom-0 w-px bg-gray-200 dark:bg-gray-700"></div>

        <ul class="space-y-6 relative">
          <li v-for="entry in history" :key="entry.id" class="pl-8 relative">
            <!-- Timeline Dot -->
            <div
              class="absolute left-0 top-1.5 w-5 h-5 rounded-full border-2 border-white dark:border-gray-800 flex items-center justify-center z-10"
              :class="getActionBadgeClass(entry.action)"
            >
              <div class="w-1.5 h-1.5 rounded-full bg-current"></div>
            </div>

            <div class="flex flex-col">
              <span class="text-xs font-bold text-gray-900 dark:text-gray-100 flex items-center gap-1">
                {{ entry.changed_by || 'Unknown' }}
                <span class="text-[10px] font-normal px-1.5 py-0.5 rounded uppercase" :class="getActionBadgeClass(entry.action)">
                  {{ entry.action }}
                </span>
              </span>
              <span class="text-[10px] text-gray-500 dark:text-gray-400">
                {{ entry.change_time ? formatDate(entry.change_time) : 'N/A' }}
              </span>
              <p v-if="entry.message" class="text-xs text-gray-600 dark:text-gray-400 mt-1 line-clamp-2 italic">
                "{{ entry.message }}"
              </p>
            </div>
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>
