<script setup lang="ts">
defineProps<{
  connected: boolean
}>()
</script>

<template>
  <div class="flex items-center gap-1 text-xs">
    <div
      :class="connected ? 'bg-green-500' : 'bg-red-500'"
      class="w-2 h-2 rounded-full"
    ></div>
    <span :class="connected ? 'text-green-500' : 'text-red-500'">
      {{ connected ? 'Live' : 'Offline' }}
    </span>
  </div>
</template>
