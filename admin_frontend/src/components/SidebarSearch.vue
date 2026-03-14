<template>
  <div class="relative mb-4">
    <input
      v-model="search"
      type="text"
      placeholder="Search..."
      class="w-full px-3 py-2 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-primary-500"
    />
    <svg class="absolute right-3 top-3 w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <circle cx="11" cy="11" r="8" stroke-width="2"/>
      <line x1="21" y1="21" x2="16.65" y2="16.65" stroke-width="2"/>
    </svg>
  </div>
</template>

<script setup lang="ts">
import { ref, defineProps, watch } from 'vue'

const props = defineProps<{
  modelValue: string
}>()

const emit = defineEmits(['update:modelValue'])

const search = ref(props.modelValue)

watch(search, (val) => {
  emit('update:modelValue', val)
})
watch(() => props.modelValue, (val) => {
  if (val !== search.value) search.value = val
})
</script>

<style scoped>
input::-webkit-search-cancel-button {
  display: none;
}
</style>
