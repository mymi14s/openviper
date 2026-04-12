import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface AlertAction {
  label: string
  to: string
}

export interface Alert {
  id: number
  type: 'error' | 'warning' | 'info'
  title: string
  message: string
  action?: AlertAction
}

export const useAlertsStore = defineStore('alerts', () => {
  const current = ref<Alert | null>(null)
  let nextId = 0

  function show(options: Omit<Alert, 'id'>): void {
    current.value = { ...options, id: ++nextId }
  }

  function dismiss(): void {
    current.value = null
  }

  return { current, show, dismiss }
})
