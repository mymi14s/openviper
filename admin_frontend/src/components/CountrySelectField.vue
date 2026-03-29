<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'

const props = defineProps<{
  modelValue: string | null
  choices: Array<{ value: string; label: string }>
  disabled?: boolean
  required?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string | null]
}>()

const searchQuery = ref('')
const showList = ref(false)
const container = ref<HTMLElement | null>(null)
const dropdownStyle = ref<Record<string, string>>({})

function countryFlag(code: string): string {
  if (!code || code.length !== 2) return ''
  const a = code.charCodeAt(0) - 65
  const b = code.charCodeAt(1) - 65
  if (a < 0 || a > 25 || b < 0 || b > 25) return ''
  return String.fromCodePoint(0x1f1e6 + a) + String.fromCodePoint(0x1f1e6 + b)
}

const selectedChoice = computed(() =>
  props.choices.find((c) => String(c.value) === String(props.modelValue ?? '')) ?? null
)

const filteredChoices = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return props.choices
  return props.choices.filter(
    (c) =>
      c.label.toLowerCase().includes(q) ||
      c.value.toLowerCase().includes(q)
  )
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
  emit('update:modelValue', choice.value)
  showList.value = false
  searchQuery.value = ''
}

function clearSelection() {
  if (props.disabled) return
  emit('update:modelValue', null)
  showList.value = false
  searchQuery.value = ''
}

function handleClickOutside(event: MouseEvent) {
  if (container.value && !container.value.contains(event.target as Node)) {
    const dropdown = document.querySelector('.country-select-dropdown')
    if (dropdown && dropdown.contains(event.target as Node)) return
    showList.value = false
    searchQuery.value = ''
  }
}

function handleGlobalUpdate() {
  if (showList.value) updateDropdownPosition()
}

onMounted(() => {
  document.addEventListener('mousedown', handleClickOutside)
  window.addEventListener('scroll', handleGlobalUpdate, true)
  window.addEventListener('resize', handleGlobalUpdate)
})

onUnmounted(() => {
  document.removeEventListener('mousedown', handleClickOutside)
  window.removeEventListener('scroll', handleGlobalUpdate, true)
  window.removeEventListener('resize', handleGlobalUpdate)
})

watch(showList, (open) => {
  if (open) updateDropdownPosition()
})
</script>

<template>
  <div ref="container" class="relative">
    <!-- Trigger button -->
    <div
      class="w-full flex items-center justify-between px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md
             bg-white dark:bg-gray-800 text-sm cursor-pointer select-none
             focus-within:ring-2 focus-within:ring-primary-500 focus-within:border-primary-500"
      :class="disabled ? 'opacity-60 cursor-not-allowed bg-gray-100 dark:bg-gray-700' : 'hover:border-gray-400 dark:hover:border-gray-500'"
      @click="openList"
    >
      <span v-if="selectedChoice" class="text-gray-900 dark:text-gray-100 flex items-center gap-1.5">
        <span class="text-base leading-none">{{ countryFlag(selectedChoice.value) }}</span>
        <span class="font-mono text-xs text-gray-500 dark:text-gray-400 uppercase">{{ selectedChoice.value }}</span>
        <span>{{ selectedChoice.label }}</span>
      </span>
      <span v-else class="text-gray-400 dark:text-gray-500">Select country…</span>

      <div class="flex items-center gap-1 ml-2 shrink-0">
        <!-- Clear button -->
        <button
          v-if="modelValue && !disabled"
          type="button"
          class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
          @click.stop="clearSelection"
          title="Clear"
        >
          <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
        <!-- Chevron -->
        <svg class="h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
        </svg>
      </div>
    </div>

    <!-- Dropdown teleported to body -->
    <Teleport to="body">
      <div
        v-if="showList && !disabled"
        class="country-select-dropdown bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-md shadow-lg flex flex-col overflow-hidden"
        :style="dropdownStyle"
      >
        <!-- Search input -->
        <div class="p-2 border-b border-gray-100 dark:border-gray-700">
          <input
            type="text"
            v-model="searchQuery"
            placeholder="Search country or code…"
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
            No countries found
          </li>
          <li
            v-for="choice in filteredChoices"
            :key="choice.value"
            class="px-3 py-1.5 text-sm text-gray-900 dark:text-gray-100 cursor-pointer flex items-center gap-2
                   hover:bg-primary-50 dark:hover:bg-primary-900/40"
            :class="String(choice.value) === String(modelValue ?? '') ? 'bg-primary-50 dark:bg-primary-900/20 font-medium' : ''"
            @click="selectChoice(choice)"
          >
            <span class="text-base leading-none w-6 shrink-0">{{ countryFlag(choice.value) }}</span>
            <span class="font-mono text-xs text-gray-400 dark:text-gray-500 uppercase w-7 shrink-0">{{ choice.value }}</span>
            <span class="truncate">{{ choice.label }}</span>
          </li>
        </ul>
      </div>
    </Teleport>
  </div>
</template>
