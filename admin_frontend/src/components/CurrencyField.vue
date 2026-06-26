<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useClickOutside } from '@/composables/useClickOutside'

const props = defineProps<{
  modelValue: string | number | null
  choices: Array<{ value: string; label: string }>
  defaultCurrency?: string
  currencyFieldName?: string
  disabled?: boolean
  required?: boolean
  decimalPlaces?: number
  allowNegative?: boolean
  currencyValue?: string | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string | null]
  'update:currency': [value: string | null]
}>()

const searchQuery = ref('')
const showList = ref(false)
const container = ref<HTMLElement | null>(null)
const dropdownStyle = ref<Record<string, string>>({})

const selectedCurrency = computed(() => {
  const code = props.currencyValue ?? props.defaultCurrency ?? ''
  return props.choices.find((c) => String(c.value) === String(code)) ?? null
})

const filteredChoices = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return props.choices
  return props.choices.filter(
    (c) =>
      c.label.toLowerCase().includes(q) ||
      c.value.toLowerCase().includes(q),
  )
})

const step = computed(() => {
  if (props.decimalPlaces) {
    return (10 ** -props.decimalPlaces).toString()
  }
  return '0.01'
})

function updateDropdownPosition() {
  if (!container.value) return
  const rect = container.value.getBoundingClientRect()
  dropdownStyle.value = {
    position: 'fixed',
    top: `${rect.bottom + 2}px`,
    left: `${rect.left}px`,
    width: `${rect.width}px`,
    zIndex: '99998',
  }
}

function openList() {
  if (props.disabled) return
  showList.value = true
  searchQuery.value = ''
  updateDropdownPosition()
}

function selectChoice(choice: { value: string; label: string }) {
  emit('update:currency', choice.value)
  showList.value = false
  searchQuery.value = ''
}

function handleAmountInput(event: Event) {
  const target = event.target as HTMLInputElement
  const val = target.value
  if (val === '') {
    emit('update:modelValue', null)
  } else {
    emit('update:modelValue', val)
  }
}

useClickOutside(container, (event: MouseEvent) => {
  const dropdown = document.querySelector('.currency-select-dropdown')
  if (dropdown && dropdown.contains(event.target as Node)) return
  showList.value = false
  searchQuery.value = ''
})

function handleGlobalUpdate() {
  if (showList.value) updateDropdownPosition()
}

onMounted(() => {
  window.addEventListener('scroll', handleGlobalUpdate, true)
  window.addEventListener('resize', handleGlobalUpdate)
})

onUnmounted(() => {
  window.removeEventListener('scroll', handleGlobalUpdate, true)
  window.removeEventListener('resize', handleGlobalUpdate)
})

watch(showList, (open) => {
  if (open) updateDropdownPosition()
})
</script>

<template>
  <div ref="container" class="flex">
    <!-- Amount input -->
    <input
      type="number"
      :value="modelValue ?? ''"
      :disabled="disabled"
      :required="required"
      :step="step"
      :min="allowNegative ? undefined : 0"
      class="flex-1 px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-l-md
             bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 text-sm
             focus:outline-none focus:ring-1 focus:ring-primary-500 focus:border-primary-500"
      @input="handleAmountInput"
    />

    <!-- Currency selector trigger -->
    <div
      class="flex items-center gap-1 px-3 py-2 border border-l-0 border-gray-300 dark:border-gray-600 rounded-r-md
             bg-gray-50 dark:bg-gray-700 text-sm cursor-pointer select-none
             hover:border-gray-400 dark:hover:border-gray-500"
      :class="disabled ? 'opacity-60 cursor-not-allowed' : ''"
      @click="openList"
    >
      <span v-if="selectedCurrency" class="text-gray-700 dark:text-gray-200 font-mono text-xs uppercase">
        {{ selectedCurrency.value }}
      </span>
      <span v-else class="text-gray-400 dark:text-gray-500">---</span>

      <svg class="h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
      </svg>
    </div>

    <!-- Dropdown teleported to body -->
    <Teleport to="body">
      <div
        v-if="showList && !disabled"
        class="currency-select-dropdown bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-md shadow-lg flex flex-col overflow-hidden"
        :style="dropdownStyle"
      >
        <!-- Search input -->
        <div class="p-2 border-b border-gray-100 dark:border-gray-700">
          <input
            type="text"
            v-model="searchQuery"
            aria-label="Search currency"
            placeholder="Search currency or code..."
            autofocus
            class="w-full px-2.5 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded
                   bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100
                   placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-primary-500"
            @click.stop
          />
        </div>

        <!-- Options list -->
        <ul class="max-h-56 overflow-y-auto py-1">
          <li v-if="filteredChoices.length === 0" class="px-3 py-2 text-sm text-gray-400 dark:text-gray-500">
            No currencies found
          </li>
          <li
            v-for="choice in filteredChoices"
            :key="choice.value"
            class="px-3 py-1.5 text-sm text-gray-900 dark:text-gray-100 cursor-pointer flex items-center gap-2
                   hover:bg-primary-50 dark:hover:bg-primary-900/40"
            :class="String(choice.value) === String(currencyValue ?? defaultCurrency ?? '') ? 'bg-primary-50 dark:bg-primary-900/20 font-medium' : ''"
            @click="selectChoice(choice)"
          >
            <span class="font-mono text-xs text-gray-500 dark:text-gray-400 uppercase w-7 shrink-0">{{ choice.value }}</span>
            <span class="truncate">{{ choice.label }}</span>
          </li>
        </ul>
      </div>
    </Teleport>
  </div>
</template>
