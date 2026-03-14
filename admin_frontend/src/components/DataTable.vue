<script setup lang="ts">
import { computed } from 'vue'
import type { ModelConfig, ModelInstance } from '@/types/admin'
import { formatFieldName } from '@/utils/formatters'

const props = defineProps<{
  model: ModelConfig
  instances: ModelInstance[]
  loading: boolean
  selectable?: boolean
  selectedIds?: Array<string | number>
}>()

const emit = defineEmits<{
  'row-click': [instance: ModelInstance]
  'selection-change': [ids: Array<string | number>]
}>()

const allSelected = computed(() => {
  if (!props.selectable || props.instances.length === 0) return false
  return props.instances.every((i) => props.selectedIds?.includes(i.id))
})

const someSelected = computed(() => {
  if (!props.selectable || props.instances.length === 0) return false
  return props.instances.some((i) => props.selectedIds?.includes(i.id)) && !allSelected.value
})

function toggleAll() {
  if (allSelected.value) {
    emit('selection-change', [])
  } else {
    emit('selection-change', props.instances.map((i) => i.id))
  }
}

function toggleRow(instance: ModelInstance) {
  const currentIds = props.selectedIds || []
  if (currentIds.includes(instance.id)) {
    emit('selection-change', currentIds.filter((id) => id !== instance.id))
  } else {
    emit('selection-change', [...currentIds, instance.id])
  }
}

function isSelected(instance: ModelInstance): boolean {
  return props.selectedIds?.includes(instance.id) ?? false
}

function formatValue(value: any): string {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (value instanceof Date) return value.toLocaleDateString()

  // For objects (including JSON field values), format nicely
  if (typeof value === 'object') {
    const jsonStr = JSON.stringify(value)
    // Truncate long JSON for list view
    return jsonStr.length > 60 ? jsonStr.slice(0, 60) + '...' : jsonStr
  }

  // Truncate long strings
  const str = String(value)
  return str.length > 100 ? str.slice(0, 100) + '...' : str
}

function getColumnStyle(fieldName: string): string | undefined {
  return props.model.list_display_styles?.[fieldName]
}

function getStatusBadgeClass(status: any): string {
  const s = String(status).toLowerCase()
  if (s === 'success' || s === 'completed' || s === 'done') {
    return 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
  }
  if (s === 'failed' || s === 'error' || s === 'failure') {
    return 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400'
  }
  return 'bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-400' // Pending, etc.
}

function getDisplayColumns(): string[] {
  if (props.model.list_display.length > 0) {
    return props.model.list_display
  }
  // Default to first few fields
  return props.model.fields.slice(0, 5).map((f) => f.name)
}

function getFieldLabel(fieldName: string): string {
  const field = props.model.fields.find((f) => f.name === fieldName)
  return field?.label || formatFieldName(fieldName)
}
</script>

<template>
  <div class="overflow-x-auto">
    <table class="table">
      <thead>
        <tr>
          <th v-if="selectable" class="w-12">
            <input
              type="checkbox"
              :checked="allSelected"
              :indeterminate="someSelected"
              class="rounded border-gray-300 dark:border-gray-600"
              @change="toggleAll"
            />
          </th>
          <th
            v-for="column in getDisplayColumns()"
            :key="column"
          >
            {{ getFieldLabel(column) }}
          </th>
        </tr>
      </thead>
      <tbody class="divide-y divide-gray-200 dark:divide-gray-700">
        <!-- Loading state -->
        <tr v-if="loading">
          <td :colspan="getDisplayColumns().length + (selectable ? 1 : 0)" class="text-center py-8">
            <svg class="animate-spin w-6 h-6 text-primary-600 mx-auto" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
            </svg>
          </td>
        </tr>

        <!-- Empty state -->
        <tr v-else-if="instances.length === 0">
          <td :colspan="getDisplayColumns().length + (selectable ? 1 : 0)" class="text-center py-8">
            <p class="text-gray-500 dark:text-gray-400">No items found</p>
          </td>
        </tr>

        <!-- Data rows -->
        <tr
          v-for="instance in instances"
          v-else
          :key="instance.id"
          class="cursor-pointer"
          @click="emit('row-click', instance)"
        >
          <td v-if="selectable" @click.stop>
            <input
              type="checkbox"
              :checked="isSelected(instance)"
              class="rounded border-gray-300 dark:border-gray-600"
              @change="toggleRow(instance)"
            />
          </td>
          <td v-for="column in getDisplayColumns()" :key="column">
            <template v-if="getColumnStyle(column) === 'status_badge'">
              <span
                :class="getStatusBadgeClass(instance[column])"
                class="px-2 py-0.5 rounded text-xs font-semibold uppercase tracking-wider inline-block"
              >
                {{ instance[column] }}
              </span>
            </template>
            <template v-else-if="typeof instance[column] === 'boolean'">
              <div class="flex items-center">
                <span v-if="instance[column]" class="text-green-500">
                  <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                    <path
                      fill-rule="evenodd"
                      d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                      clip-rule="evenodd"
                    />
                  </svg>
                </span>
                <span v-else class="text-red-500">
                  <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                    <path
                      fill-rule="evenodd"
                      d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z"
                      clip-rule="evenodd"
                    />
                  </svg>
                </span>
              </div>
            </template>
            <template v-else>
              {{ formatValue(instance[column]) }}
            </template>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
