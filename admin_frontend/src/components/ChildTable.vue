<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import type { ModelField } from '@/types/admin'
import ForeignKeyField from '@/components/ForeignKeyField.vue'
import { formatFieldName } from '@/utils/formatters'

interface ChildTableConfig {
  name: string
  label: string
  model: string
  fk_name: string | null
  fields: Record<string, ModelField>
  display_fields: string[]
  readonly_fields?: string[]
}

const props = defineProps<{
  config: ChildTableConfig
  modelValue: any[]
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: any[]]
}>()

const rows = ref<any[]>([])
const currentPage = ref(1)
const itemsPerPage = ref(10)
const selectedIndices = ref<Set<number>>(new Set())

// Sync local rows with modelValue
watch(() => props.modelValue, (newVal) => {
  if (JSON.stringify(newVal) !== JSON.stringify(rows.value)) {
    rows.value = newVal ? [...newVal] : []
    selectedIndices.value.clear()
  }
}, { immediate: true })

// Emit changes to parent
function updateRows() {
  emit('update:modelValue', rows.value)
}

const totalPages = computed(() => Math.ceil(rows.value.length / itemsPerPage.value) || 1)

const visiblePages = computed(() => {
  const maxVisible = 10
  const pages: number[] = []
  
  if (totalPages.value <= maxVisible) {
    for (let i = 1; i <= totalPages.value; i++) pages.push(i)
  } else {
    let start = Math.max(1, currentPage.value - Math.floor(maxVisible / 2))
    let end = start + maxVisible - 1
    
    if (end > totalPages.value) {
      end = totalPages.value
      start = Math.max(1, end - maxVisible + 1)
    }
    
    for (let i = start; i <= end; i++) pages.push(i)
  }
  return pages
})

const paginatedRows = computed(() => {
  const start = (currentPage.value - 1) * itemsPerPage.value
  const end = start + itemsPerPage.value
  return rows.value.slice(start, end)
})

function setPage(page: number) {
  if (page >= 1 && page <= totalPages.value) {
    currentPage.value = page
  }
}

const isAllSelected = computed(() => {
  if (paginatedRows.value.length === 0) return false
  return paginatedRows.value.every((_, idx) => {
    const globalIdx = (currentPage.value - 1) * itemsPerPage.value + idx
    return selectedIndices.value.has(globalIdx)
  })
})

const isSomeSelected = computed(() => {
  return selectedIndices.value.size > 0 && !isAllSelected.value
})

function toggleSelectAll() {
  if (isAllSelected.value) {
    paginatedRows.value.forEach((_, idx) => {
      const globalIdx = (currentPage.value - 1) * itemsPerPage.value + idx
      selectedIndices.value.delete(globalIdx)
    })
  } else {
    paginatedRows.value.forEach((_, idx) => {
      const globalIdx = (currentPage.value - 1) * itemsPerPage.value + idx
      selectedIndices.value.add(globalIdx)
    })
  }
}

function toggleSelectRow(idx: number) {
  const globalIdx = (currentPage.value - 1) * itemsPerPage.value + idx
  if (selectedIndices.value.has(globalIdx)) {
    selectedIndices.value.delete(globalIdx)
  } else {
    selectedIndices.value.add(globalIdx)
  }
}

function deleteSelected() {
  if (!confirm(`Are you sure you want to delete ${selectedIndices.value.size} items?`)) return
  
  const indicesToDelete = Array.from(selectedIndices.value).sort((a, b) => b - a)
  indicesToDelete.forEach(idx => {
    rows.value.splice(idx, 1)
  })
  
  selectedIndices.value.clear()
  updateRows()
  
  if (currentPage.value > totalPages.value) {
    currentPage.value = totalPages.value || 1
  }
}

function addRow() {
  const newRow: any = {}
  props.config.display_fields.forEach(fieldName => {
    if (fieldName !== 'id') {
      newRow[fieldName] = null
    }
  })
  rows.value.push(newRow)
  updateRows()
  // Go to last page to see the new row
  currentPage.value = totalPages.value
}

function removeRow(index: number) {
  // Calculate global index from local paginated index
  const globalIndex = (currentPage.value - 1) * itemsPerPage.value + index
  rows.value.splice(globalIndex, 1)
  updateRows()
  
  // Adjust current page if it's now out of bounds
  if (currentPage.value > totalPages.value) {
    currentPage.value = totalPages.value
  }
}

function updateField(localIndex: number, fieldName: string, value: any) {
  const globalIndex = (currentPage.value - 1) * itemsPerPage.value + localIndex
  rows.value[globalIndex][fieldName] = value
  updateRows()
}

function getFieldType(field: ModelField): string {
  // Map model field types to input types
  const typeMap: Record<string, string> = {
    // Generic types (lowercase variants)
    text: 'text',
    string: 'text',
    email: 'email',
    url: 'url',
    number: 'number',
    password: 'password',
    date: 'date',
    datetime: 'datetime-local',
    time: 'time',
    boolean: 'checkbox',
    textarea: 'textarea',
    select: 'select',
    file: 'file',
    image: 'file',

    // Field names (case-sensitive as returned by backend)
    CharField: 'text',
    SlugField: 'text',
    EmailField: 'email',
    URLField: 'url',
    IntegerField: 'number',
    BigIntegerField: 'number',
    FloatField: 'number',
    DecimalField: 'number',
    TextField: 'textarea',
    JSONField: 'textarea',
    BooleanField: 'checkbox',
    DateField: 'date',
    DateTimeField: 'datetime-local',
    TimeField: 'time',
    ForeignKey: 'select',
  }

  // Fallback to lowercase check if not found
  return typeMap[field.type] || typeMap[field.type.charAt(0).toUpperCase() + field.type.slice(1)] || 'text'
}

function getFieldComponent(field: ModelField): string {
  if (field.related_model) return 'foreignkey'
  const type = getFieldType(field)
  if (field.choices && field.choices.length > 0) return 'select'
  if (type === 'checkbox') return 'checkbox'
  if (type === 'textarea') return 'textarea'
  return 'input'
}

function formatDateTimeValue(value: any, fieldType: string): string {
  if (!value) return ''
  
  // Handle datetime-local fields
  if (fieldType === 'datetime-local') {
    const date = new Date(value)
    if (isNaN(date.getTime())) return ''
    
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    const hours = String(date.getHours()).padStart(2, '0')
    const minutes = String(date.getMinutes()).padStart(2, '0')
    
    return `${year}-${month}-${day}T${hours}:${minutes}`
  }
  
  // Handle date fields
  if (fieldType === 'date') {
    const date = new Date(value)
    if (isNaN(date.getTime())) return ''
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    return `${year}-${month}-${day}`
  }
  
  return String(value)
}

function parseDateTimeValue(value: string, fieldType: string): any {
  if (!value) return null
  if (fieldType === 'datetime-local') {
    const date = new Date(value)
    if (isNaN(date.getTime())) return value
    return date.toISOString()
  }
  return value
}

function handleDateTimeChange(localIndex: number, fieldName: string, value: string, fieldType: string) {
  const parsedValue = parseDateTimeValue(value, fieldType)
  updateField(localIndex, fieldName, parsedValue)
}

function isReadonly(fieldName: string): boolean {
  return props.disabled || (props.config.readonly_fields?.includes(fieldName) ?? false)
}

function getFieldLabel(fieldName: string): string {
  return props.config.fields[fieldName]?.label || formatFieldName(fieldName)
}

function formatValueForDisplay(value: any, field: ModelField): string {
  if (value === null || value === undefined) return ''

  // For JSON fields, pretty-print objects
  if (field.type === 'JSONField') {
    if (typeof value === 'object') {
      return JSON.stringify(value, null, 2)
    }
    return String(value)
  }

  // For regular textareas with objects
  if (typeof value === 'object') {
    return JSON.stringify(value, null, 2)
  }

  return String(value)
}

function parseValueFromDisplay(value: string, field: ModelField): any {
  if (!value) return field.type === 'JSONField' ? null : value

  // For JSON fields, parse the JSON string
  if (field.type === 'JSONField') {
    try {
      return JSON.parse(value)
    } catch {
      return value
    }
  }

  return value
}

function handleTextareaInput(idx: number, fieldName: string, value: string) {
  const field = props.config.fields[fieldName]
  const parsed = parseValueFromDisplay(value, field)
  updateField(idx, fieldName, parsed)
}
</script>

<template>
  <div class="mt-8 border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-800">
    <div class="px-4 py-3 border-b border-gray-200 dark:border-gray-700 flex justify-between items-center bg-gray-50 dark:bg-gray-900">
      <h3 class="text-sm font-semibold text-gray-900 dark:text-gray-100 uppercase tracking-wider">
        {{ config.label }}
      </h3>
      <div class="flex items-center space-x-2">
        <button
          v-if="selectedIndices.size > 0"
          type="button"
          @click="deleteSelected"
          class="inline-flex items-center px-3 py-1.5 border border-red-300 dark:border-red-700 text-xs font-medium rounded shadow-sm text-red-700 dark:text-red-300 bg-white dark:bg-gray-800 hover:bg-red-50 dark:hover:bg-red-900/20 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500"
        >
          Delete Selected ({{ selectedIndices.size }})
        </button>
        <button
          type="button"
          @click="addRow"
          :disabled="disabled"
          class="inline-flex items-center px-3 py-1.5 border border-transparent text-xs font-medium rounded shadow-sm text-white bg-primary-600 hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 disabled:opacity-50"
        >
          <svg class="h-4 w-4 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
          </svg>
          Add Row
        </button>
      </div>
    </div>

    <div class="overflow-x-auto">
      <table class="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
        <thead class="bg-gray-50 dark:bg-gray-900">
          <tr>
            <th scope="col" class="px-3 py-3 text-left">
              <input
                type="checkbox"
                :checked="isAllSelected"
                :indeterminate="isSomeSelected"
                @change="toggleSelectAll"
                class="h-4 w-4 rounded border-gray-300 dark:border-gray-600 text-primary-600 focus:ring-primary-500"
              />
            </th>
            <th 
              v-for="fieldName in config.display_fields" 
              :key="fieldName"
              scope="col" 
              class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 tracking-wider"
              v-show="fieldName !== 'id'"
            >
              {{ getFieldLabel(fieldName) }}
              <span v-if="config.fields[fieldName]?.required" class="text-red-500">*</span>
            </th>
            <th scope="col" class="relative px-4 py-3">
              <span class="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <TransitionGroup tag="tbody" name="child-row" class="divide-y divide-gray-200 dark:divide-gray-700">
          <tr v-if="rows.length === 0" key="empty">
            <td :colspan="config.display_fields.length + 2" class="px-4 py-8 text-center text-sm text-gray-500 dark:text-gray-400">
              No records found. Click "Add Row" to create one.
            </td>
          </tr>
          <tr v-for="(row, idx) in paginatedRows" :key="row.id ?? `row-${(currentPage - 1) * itemsPerPage + idx}`" class="hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors">
            <td class="px-3 py-2 whitespace-nowrap">
              <input
                type="checkbox"
                :checked="selectedIndices.has((currentPage - 1) * itemsPerPage + idx)"
                @change="toggleSelectRow(idx)"
                class="h-4 w-4 rounded border-gray-300 dark:border-gray-600 text-primary-600 focus:ring-primary-500"
              />
            </td>
            <td 
              v-for="fieldName in config.display_fields" 
              :key="fieldName"
              v-show="fieldName !== 'id'"
              class="px-4 py-2 whitespace-nowrap"
            >
              <template v-if="config.fields[fieldName]">
                <!-- ForeignKey -->
                <ForeignKeyField
                  v-if="getFieldComponent(config.fields[fieldName]) === 'foreignkey'"
                  :model-value="row[fieldName]"
                  :related-model="config.fields[fieldName].related_model || ''"
                  :disabled="isReadonly(fieldName)"
                  class="min-w-[150px]"
                  @update:model-value="updateField(idx, fieldName, $event)"
                />
                
                <!-- Select / Choices -->
                <select
                  v-else-if="getFieldComponent(config.fields[fieldName]) === 'select'"
                  :value="row[fieldName]"
                  :disabled="isReadonly(fieldName)"
                  :required="config.fields[fieldName].required"
                  @change="updateField(idx, fieldName, ($event.target as HTMLSelectElement).value)"
                  class="block w-full px-2 py-1.5 text-sm border-gray-300 dark:border-gray-600 rounded-md focus:ring-primary-500 focus:border-primary-500 dark:bg-gray-700 dark:text-white"
                >
                  <option value="">Select...</option>
                  <option
                    v-for="choice in config.fields[fieldName].choices"
                    :key="choice.value"
                    :value="choice.value"
                  >
                    {{ choice.label }}
                  </option>
                </select>

                <!-- Checkbox -->
                <div v-else-if="getFieldComponent(config.fields[fieldName]) === 'checkbox'" class="flex justify-center">
                  <input
                    type="checkbox"
                    :checked="row[fieldName]"
                    :disabled="isReadonly(fieldName)"
                    @change="updateField(idx, fieldName, ($event.target as HTMLInputElement).checked)"
                    class="h-4 w-4 rounded border-gray-300 dark:border-gray-600 text-primary-600 focus:ring-primary-500"
                  />
                </div>
                
                <!-- Textarea -->
                <textarea
                  v-else-if="getFieldComponent(config.fields[fieldName]) === 'textarea'"
                  :value="formatValueForDisplay(row[fieldName], config.fields[fieldName])"
                  :disabled="isReadonly(fieldName)"
                  @input="handleTextareaInput(idx, fieldName, ($event.target as HTMLTextAreaElement).value)"
                  rows="2"
                  class="block w-full px-2 py-1.5 text-sm font-mono border-gray-300 dark:border-gray-600 rounded-md focus:ring-primary-500 focus:border-primary-500 dark:bg-gray-700 dark:text-white min-w-[200px]"
                ></textarea>

                <!-- Input -->
                <div v-else class="space-y-1">
                  <input
                    :type="getFieldType(config.fields[fieldName])"
                    :value="getFieldType(config.fields[fieldName]) === 'file' ? undefined : formatDateTimeValue(row[fieldName], getFieldType(config.fields[fieldName]))"
                    :disabled="isReadonly(fieldName)"
                    :required="config.fields[fieldName].required"
                    @input="getFieldType(config.fields[fieldName]) === 'file' ? (e: any) => updateField(idx, fieldName, (e.target as any).files[0]) : handleDateTimeChange(idx, fieldName, ($event.target as HTMLInputElement).value, getFieldType(config.fields[fieldName]))"
                    class="block w-full px-2 py-1.5 text-sm border-gray-300 dark:border-gray-600 rounded-md focus:ring-primary-500 focus:border-primary-500 dark:bg-gray-700 dark:text-white"
                  />
                  <p v-if="config.fields[fieldName].help_text" class="text-[10px] text-gray-400 italic">
                    {{ config.fields[fieldName].help_text }}
                  </p>
                </div>
              </template>
              <template v-else>
                 <span class="text-xs text-gray-400">Unknown Field</span>
              </template>
            </td>
            <td class="px-4 py-2 whitespace-nowrap text-right text-sm font-medium">
              <button
                type="button"
                @click="removeRow(idx)"
                :disabled="disabled"
                class="text-red-600 hover:text-red-900 dark:text-red-400 dark:hover:text-red-300 disabled:opacity-50"
              >
                <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
              </button>
            </td>
          </tr>
        </TransitionGroup>
      </table>
    </div>

    <!-- Pagination Controls -->
    <div v-if="totalPages > 1" class="px-4 py-3 bg-gray-50 dark:bg-gray-900 border-t border-gray-200 dark:border-gray-700 flex items-center justify-between sm:px-6">
      <div class="flex-1 flex justify-between sm:hidden">
        <button
          type="button"
          @click.prevent="setPage(currentPage - 1)"
          :disabled="currentPage === 1"
          class="relative inline-flex items-center px-4 py-2 border border-gray-300 dark:border-gray-600 text-sm font-medium rounded-md text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50"
        >
          Previous
        </button>
        <button
          type="button"
          @click.prevent="setPage(currentPage + 1)"
          :disabled="currentPage === totalPages"
          class="ml-3 relative inline-flex items-center px-4 py-2 border border-gray-300 dark:border-gray-600 text-sm font-medium rounded-md text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50"
        >
          Next
        </button>
      </div>
      <div class="hidden sm:flex-1 sm:flex sm:items-center sm:justify-between">
        <div>
          <p class="text-sm text-gray-700 dark:text-gray-300">
            Showing
            <span class="font-medium">{{ (currentPage - 1) * itemsPerPage + 1 }}</span>
            to
            <span class="font-medium">{{ Math.min(currentPage * itemsPerPage, rows.length) }}</span>
            of
            <span class="font-medium">{{ rows.length }}</span>
            results
          </p>
        </div>
        <div>
          <nav class="relative z-0 inline-flex rounded-md shadow-sm -space-x-px" aria-label="Pagination">
            <button
              type="button"
              @click.prevent="setPage(currentPage - 1)"
              :disabled="currentPage === 1"
              class="relative inline-flex items-center px-2 py-2 rounded-l-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-sm font-medium text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50"
            >
              <span class="sr-only">Previous</span>
              <svg class="h-5 w-5" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                <path fill-rule="evenodd" d="M12.707 5.293a1 1 0 010 1.414L9.414 10l3.293 3.293a1 1 0 01-1.414 1.414l-4-4a1 1 0 010-1.414l4-4a1 1 0 011.414 0z" clip-rule="evenodd" />
              </svg>
            </button>
            
            <button
              v-for="page in visiblePages"
              :key="page"
              type="button"
              @click.prevent="setPage(page)"
              :class="[
                page === currentPage 
                  ? 'z-10 bg-primary-50 dark:bg-primary-900 border-primary-500 text-primary-600 dark:text-primary-300' 
                  : 'bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-600 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700',
                'relative inline-flex items-center px-4 py-2 border text-sm font-medium'
              ]"
            >
              {{ page }}
            </button>

            <button
              type="button"
              @click.prevent="setPage(currentPage + 1)"
              :disabled="currentPage === totalPages"
              class="relative inline-flex items-center px-2 py-2 rounded-r-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-sm font-medium text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50"
            >
              <span class="sr-only">Next</span>
              <svg class="h-5 w-5" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                <path fill-rule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" clip-rule="evenodd" />
              </svg>
            </button>
          </nav>
        </div>
      </div>
    </div>
  </div>
</template>
