import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ThemeMode } from '@/types/admin'

const THEME_KEY = 'openviper_admin_theme'

export const useThemeStore = defineStore('theme', () => {
  const mode = ref<ThemeMode>((localStorage.getItem(THEME_KEY) as ThemeMode) || 'system')

  const isDark = computed(() => {
    if (mode.value === 'dark') return true
    if (mode.value === 'light') return false
    return window.matchMedia('(prefers-color-scheme: dark)').matches
  })

  function applyTheme(): void {
    document.documentElement.classList.toggle('dark', isDark.value)
  }
  function setMode(newMode: ThemeMode): void {
    mode.value = newMode
    localStorage.setItem(THEME_KEY, newMode)
    applyTheme()
  }

  function toggleDark(): void {
    if (mode.value === 'system') {
      setMode(isDark.value ? 'light' : 'dark')
    } else {
      setMode(mode.value === 'dark' ? 'light' : 'dark')
    }
  }

  function init(): void {
    applyTheme()
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
      if (mode.value === 'system') applyTheme()
    })
  }

  return {
    mode,
    isDark,
    setMode,
    toggleDark,
    init,
  }
})
