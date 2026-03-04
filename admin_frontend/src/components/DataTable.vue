<script setup lang="ts">
import { computed } from 'vue'
import type { ModelConfig, ModelInstance } from '@/types/admin'

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

function formatValue(value: any, _field: string): string {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (value instanceof Date) return value.toLocaleDateString()
  if (typeof value === 'object') return JSON.stringify(value)
  
  // Truncate long strings
  const str = String(value)
  return str.length > 100 ? str.slice(0, 100) + '...' : str
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
  return field?.label || field?.name || fieldName.replace(/_/g, ' ')
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
            class="capitalize"
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
            {{ formatValue(instance[column], column) }}
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
