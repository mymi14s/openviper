<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { useAlertsStore } from '@/stores/alerts'

const alertsStore = useAlertsStore()

const alert = computed(() => alertsStore.current)

const iconConfig = computed(() => {
  switch (alert.value?.type) {
    case 'warning':
      return {
        wrapperClass: 'bg-yellow-100 dark:bg-yellow-900/40',
        iconClass: 'text-yellow-600 dark:text-yellow-400',
        path: 'M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z',
      }
    case 'info':
      return {
        wrapperClass: 'bg-blue-100 dark:bg-blue-900/40',
        iconClass: 'text-blue-600 dark:text-blue-400',
        path: 'M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
      }
    default:
      return {
        wrapperClass: 'bg-red-100 dark:bg-red-900/40',
        iconClass: 'text-red-600 dark:text-red-400',
        path: 'M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z',
      }
  }
})

const headerClass = computed(() => {
  switch (alert.value?.type) {
    case 'warning': return 'text-yellow-900 dark:text-yellow-100'
    case 'info': return 'text-blue-900 dark:text-blue-100'
    default: return 'text-red-900 dark:text-red-100'
  }
})

const bodyClass = computed(() => {
  switch (alert.value?.type) {
    case 'warning': return 'text-yellow-800 dark:text-yellow-200'
    case 'info': return 'text-blue-800 dark:text-blue-200'
    default: return 'text-red-800 dark:text-red-200'
  }
})

const actionClass = computed(() => {
  switch (alert.value?.type) {
    case 'warning': return 'btn bg-yellow-600 hover:bg-yellow-700 text-white'
    case 'info': return 'btn bg-blue-600 hover:bg-blue-700 text-white'
    default: return 'btn bg-red-600 hover:bg-red-700 text-white'
  }
})

function handleAction() {
  alertsStore.dismiss()
}
</script>

<template>
  <Teleport to="body">
    <Transition
      enter-active-class="transition duration-200 ease-out"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition duration-150 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div
        v-if="alert"
        class="fixed inset-0 z-[9999] flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm"
        @click.self="alertsStore.dismiss()"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="`alert-title-${alert.id}`"
      >
        <Transition
          enter-active-class="transition duration-200 ease-out"
          enter-from-class="opacity-0 scale-95"
          enter-to-class="opacity-100 scale-100"
          leave-active-class="transition duration-150 ease-in"
          leave-from-class="opacity-100 scale-100"
          leave-to-class="opacity-0 scale-95"
        >
          <div
            v-if="alert"
            class="relative w-full max-w-md bg-white dark:bg-gray-800 rounded-xl shadow-2xl ring-1 ring-black/10 dark:ring-white/10 overflow-hidden"
          >
            <!-- Header strip -->
            <div class="flex items-start gap-4 p-6">
              <!-- Icon -->
              <div :class="['flex-shrink-0 flex items-center justify-center w-10 h-10 rounded-full', iconConfig.wrapperClass]">
                <svg class="w-5 h-5" :class="iconConfig.iconClass" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" :d="iconConfig.path" />
                </svg>
              </div>

              <!-- Content -->
              <div class="flex-1 min-w-0">
                <h3
                  :id="`alert-title-${alert.id}`"
                  class="text-base font-semibold"
                  :class="headerClass"
                >
                  {{ alert.title }}
                </h3>
                <p class="mt-1 text-sm" :class="bodyClass">
                  {{ alert.message }}
                </p>
              </div>

              <!-- Close button -->
              <button
                @click="alertsStore.dismiss()"
                class="flex-shrink-0 p-1 rounded-md text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                aria-label="Close alert"
              >
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <!-- Footer actions -->
            <div class="flex items-center justify-end gap-3 px-6 py-4 bg-gray-50 dark:bg-gray-700/50 border-t border-gray-100 dark:border-gray-700">
              <RouterLink
                v-if="alert.action"
                :to="alert.action.to"
                :class="[actionClass, 'flex items-center gap-1.5 text-sm']"
                @click="handleAction"
              >
                {{ alert.action.label }}
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3" />
                </svg>
              </RouterLink>
              <button
                @click="alertsStore.dismiss()"
                class="btn btn-secondary text-sm"
              >
                {{ alert.action ? 'Stay on Page' : 'OK' }}
              </button>
            </div>
          </div>
        </Transition>
      </div>
    </Transition>
  </Teleport>
</template>
