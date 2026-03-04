<script setup lang="ts">
import { ref, watch, computed, onMounted, onUnmounted } from 'vue'
import { modelsApi } from '@/api/client'

const props = defineProps<{
  modelValue: number | string | null
  relatedModel: string
  disabled?: boolean
  required?: boolean
  placeholder?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: number | string | null]
}>()

const searchQuery = ref('')
const options = ref<Array<{ value: any; label: string }>>([])
const isLoading = ref(false)
const showList = ref(false)
const selectedLabel = ref('')
const container = ref<HTMLElement | null>(null)

// Parse related_model string (e.g., "auth/user") into app_label and model_name
const parsedModel = computed(() => {
  if (!props.relatedModel) return { appLabel: '', modelName: '' }
  const parts = props.relatedModel.split('/')
  if (parts.length === 2) {
    return { appLabel: parts[0], modelName: parts[1] }
  }
  return { appLabel: 'default', modelName: props.relatedModel }
})

// Debounced search
let searchTimeout: ReturnType<typeof setTimeout> | null = null

async function searchOptions(query: string) {
  const { appLabel, modelName } = parsedModel.value
  if (!appLabel || !modelName) return

  isLoading.value = true
  try {
    options.value = await modelsApi.searchForeignKey(appLabel, modelName, query, 20)
  } catch {
    console.error('Failed to search foreign key options')
    options.value = []
  } finally {
    isLoading.value = false
  }
}

const dropdownStyle = ref<Record<string, string>>({})

function updateDropdownPosition() {
  if (!container.value) return
  const rect = container.value.getBoundingClientRect()
  dropdownStyle.value = {
    position: 'fixed',
    top: `${rect.bottom}px`,
    left: `${rect.left}px`,
    width: `${rect.width}px`,
    zIndex: '9999'
  }
}

function onSearchInput(event: Event) {
  const target = event.target as HTMLInputElement
  searchQuery.value = target.value
  showList.value = true
  
  updateDropdownPosition()

  if (searchTimeout) clearTimeout(searchTimeout)
  searchTimeout = setTimeout(() => {
    searchOptions(searchQuery.value)
  }, 300)
}

function selectOption(option: { value: any; label: string }) {
  emit('update:modelValue', option.value)
  selectedLabel.value = option.label
  searchQuery.value = option.label
  showList.value = false
}

function clearSelection() {
  if (props.disabled) return
  emit('update:modelValue', null)
  selectedLabel.value = ''
  searchQuery.value = ''
  searchOptions('')
}

async function loadInitialValue() {
  if (props.modelValue === null || props.modelValue === undefined) {
    searchQuery.value = ''
    selectedLabel.value = ''
    return
  }

  const { appLabel, modelName } = parsedModel.value
  if (!appLabel || !modelName) return

  try {
    // Attempt to find the label for the current value
    const results = await modelsApi.searchForeignKey(appLabel, modelName, '', 50)
    const found = results.find(opt => String(opt.value) === String(props.modelValue))
    if (found) {
      selectedLabel.value = found.label
      searchQuery.value = found.label
    } else {
      searchQuery.value = `#${props.modelValue}`
      selectedLabel.value = `#${props.modelValue}`
    }
  } catch {
    searchQuery.value = `#${props.modelValue}`
    selectedLabel.value = `#${props.modelValue}`
  }
}

function handleClickOutside(event: MouseEvent) {
  if (container.value && !container.value.contains(event.target as Node)) {
    // Check if click was on the teleported list
    const resultsList = document.querySelector('.foreign-key-results')
    if (resultsList && resultsList.contains(event.target as Node)) {
        return
    }
    showList.value = false
    // Reset search query to selected label if we didn't select anything
    searchQuery.value = selectedLabel.value
  }
}

function handleInputFocus() {
  if (props.disabled) return
  showList.value = true
  updateDropdownPosition()
  if (options.value.length === 0) {
    searchOptions('')
  }
}

// Add scroll/resize listeners for fixed position
function handleGlobalUpdate() {
  if (showList.value) {
    updateDropdownPosition()
  }
}

onMounted(async () => {
  document.addEventListener('mousedown', handleClickOutside)
  window.addEventListener('scroll', handleGlobalUpdate, true)
  window.addEventListener('resize', handleGlobalUpdate)
  await loadInitialValue()
})

onUnmounted(() => {
  document.removeEventListener('mousedown', handleClickOutside)
  window.removeEventListener('scroll', handleGlobalUpdate, true)
  window.removeEventListener('resize', handleGlobalUpdate)
})

watch(() => props.modelValue, () => {
  loadInitialValue()
})
</script>

<template>
  <div ref="container" class="relative">
    <div class="relative items-center flex">
      <input
        type="text"
        v-model="searchQuery"
        :disabled="disabled"
        :required="required"
        :placeholder="placeholder || 'Search...'"
        class="w-full pl-3 pr-10 py-2 border border-gray-300 dark:border-gray-600 rounded-md 
               bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100
               focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500
               disabled:bg-gray-100 dark:disabled:bg-gray-700 disabled:cursor-not-allowed text-sm"
        @input="onSearchInput"
        @focus="handleInputFocus"
      />
      
      <!-- Clear button -->
      <button
        v-if="modelValue !== null && !disabled"
        type="button"
        class="absolute right-8 p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
        @click="clearSelection"
      >
        <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>

      <!-- Dropdown indicator -->
      <div class="absolute right-3 pointer-events-none text-gray-400">
        <svg v-if="isLoading" class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        <svg v-else class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
        </svg>
      </div>
    </div>

    <!-- Results list teleported to body -->
    <Teleport to="body">
      <div
        v-if="showList && !disabled"
        class="foreign-key-results mt-1 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-md shadow-lg max-h-60 overflow-auto"
        :style="dropdownStyle"
      >
        <ul class="py-1">
          <li
            v-for="option in options"
            :key="option.value"
            class="px-3 py-2 text-sm text-gray-900 dark:text-gray-100 hover:bg-primary-50 dark:hover:bg-primary-900/40 cursor-pointer flex justify-between items-center"
            :class="{ 'bg-primary-50 dark:bg-primary-900/20': String(option.value) === String(modelValue) }"
            @click="selectOption(option)"
          >
            <span>{{ option.label }}</span>
            <span class="text-[10px] text-gray-400 font-mono">ID: {{ option.value }}</span>
          </li>
          <li v-if="options.length === 0 && !isLoading" class="px-3 py-2 text-sm text-gray-500 italic">
            No results found
          </li>
        </ul>
      </div>
    </Teleport>
  </div>
</template>
