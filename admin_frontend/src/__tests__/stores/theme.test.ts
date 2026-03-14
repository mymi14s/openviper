/**
 * Tests for theme store
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useThemeStore } from '@/stores/theme'

describe('Theme Store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    localStorage.getItem = vi.fn().mockReturnValue(null)
    localStorage.setItem = vi.fn()
    // Mock document.documentElement
    document.documentElement.classList.toggle = vi.fn()
    // Mock matchMedia
    window.matchMedia = vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
    })
  })

  describe('Initial state', () => {
    it('should have system mode by default', () => {
      const store = useThemeStore()
      // Default mode is 'system' when nothing in localStorage
      expect(store.mode).toBe('system')
    })

    it('should compute isDark based on mode', () => {
      const store = useThemeStore()
      // In light system preference, isDark should be false
      expect(store.isDark).toBe(false)
    })

    it('should load mode from localStorage', () => {
      localStorage.getItem = vi.fn().mockReturnValue('dark')
      setActivePinia(createPinia())
      const store = useThemeStore()
      expect(store.mode).toBe('dark')
    })
  })

  describe('setMode', () => {
    it('should set mode to dark', () => {
      const store = useThemeStore()
      store.setMode('dark')

      expect(store.mode).toBe('dark')
      expect(store.isDark).toBe(true)
    })

    it('should set mode to light', () => {
      const store = useThemeStore()
      store.setMode('light')

      expect(store.mode).toBe('light')
      expect(store.isDark).toBe(false)
    })

    it('should persist to localStorage', () => {
      const store = useThemeStore()
      store.setMode('dark')

      expect(localStorage.setItem).toHaveBeenCalledWith('openviper_admin_theme', 'dark')
    })
  })

  describe('toggleDark', () => {
    it('should toggle from system to opposite of current', () => {
      window.matchMedia = vi.fn().mockReturnValue({
        matches: false, // light system preference
        addEventListener: vi.fn(),
      })
      const store = useThemeStore()

      // When mode is system and system is light, toggle should set to dark
      store.toggleDark()

      expect(store.mode).toBe('dark')
    })

    it('should toggle from dark to light', () => {
      const store = useThemeStore()
      store.setMode('dark')

      store.toggleDark()

      expect(store.mode).toBe('light')
    })

    it('should toggle from light to dark', () => {
      const store = useThemeStore()
      store.setMode('light')

      store.toggleDark()

      expect(store.mode).toBe('dark')
    })
  })

  describe('init', () => {
    it('should be callable', () => {
      const store = useThemeStore()
      expect(typeof store.init).toBe('function')
    })

    it('should apply theme to document', () => {
      const store = useThemeStore()
      store.setMode('dark')
      store.init()

      expect(document.documentElement.classList.toggle).toHaveBeenCalledWith('dark', true)
    })
  })

  describe('isDark computed', () => {
    it('should be true when mode is dark', () => {
      const store = useThemeStore()
      store.setMode('dark')

      expect(store.isDark).toBe(true)
    })

    it('should be false when mode is light', () => {
      const store = useThemeStore()
      store.setMode('light')

      expect(store.isDark).toBe(false)
    })

    it('should use system preference when mode is system', () => {
      window.matchMedia = vi.fn().mockReturnValue({
        matches: true, // dark system preference
        addEventListener: vi.fn(),
      })
      setActivePinia(createPinia())
      const store = useThemeStore()

      store.setMode('system')
      expect(store.isDark).toBe(true)
    })
  })
})
