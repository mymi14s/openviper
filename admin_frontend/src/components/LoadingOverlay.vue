<script setup lang="ts">
defineProps<{
  show: boolean
}>()
</script>

<template>
  <Teleport to="body">
    <Transition name="overlay">
      <div
        v-if="show"
        class="fixed inset-0 z-[9999] flex items-center justify-center"
        aria-live="assertive"
        aria-label="Saving, please wait"
        role="status"
      >
        <!-- Backdrop -->
        <div class="absolute inset-0 bg-black/40 backdrop-blur-[2px]" />

        <!-- Spinner card -->
        <div class="relative flex flex-col items-center gap-4 rounded-2xl bg-white/90 dark:bg-gray-800/90 px-10 py-8 shadow-2xl ring-1 ring-black/5 dark:ring-white/10 mx-4 w-full max-w-[180px] sm:max-w-[200px]">
          <svg
            class="w-10 h-10 sm:w-12 sm:h-12 text-primary-600 animate-spin"
            fill="none"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <p class="text-sm font-medium text-gray-700 dark:text-gray-300 whitespace-nowrap">Saving…</p>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.overlay-enter-active,
.overlay-leave-active {
  transition: opacity 0.15s ease;
}
.overlay-enter-from,
.overlay-leave-to {
  opacity: 0;
}
</style>
