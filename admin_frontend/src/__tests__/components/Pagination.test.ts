/**
 * Tests for Pagination component
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import Pagination from '@/components/Pagination.vue'

function mountPagination(props = {}) {
  return mount(Pagination, {
    props: {
      currentPage: 1,
      totalPages: 10,
      totalItems: 100,
      perPage: 10,
      ...props,
    },
    global: {
      plugins: [createPinia()],
    },
  })
}

describe('Pagination Component', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  describe('Rendering', () => {
    it('should render info text', () => {
      const wrapper = mountPagination()

      expect(wrapper.text()).toContain('Showing')
      expect(wrapper.text()).toContain('1')
      expect(wrapper.text()).toContain('10')
      expect(wrapper.text()).toContain('100')
    })

    it('should render previous and next buttons', () => {
      const wrapper = mountPagination()

      const buttons = wrapper.findAll('button')
      expect(buttons.length).toBeGreaterThanOrEqual(2)
    })

    it('should render page numbers', () => {
      const wrapper = mountPagination({ totalPages: 5 })

      expect(wrapper.text()).toContain('1')
      expect(wrapper.text()).toContain('2')
      expect(wrapper.text()).toContain('5')
    })

    it('should show ellipsis for many pages', () => {
      const wrapper = mountPagination({
        currentPage: 5,
        totalPages: 20
      })

      expect(wrapper.text()).toContain('...')
    })
  })

  describe('Info Text Calculation', () => {
    it('should calculate correct start and end items for first page', () => {
      const wrapper = mountPagination({
        currentPage: 1,
        perPage: 10,
        totalItems: 100,
      })

      expect(wrapper.text()).toContain('Showing 1 to 10')
    })

    it('should calculate correct start and end items for middle page', () => {
      const wrapper = mountPagination({
        currentPage: 5,
        perPage: 10,
        totalItems: 100,
      })

      expect(wrapper.text()).toContain('41')
      expect(wrapper.text()).toContain('50')
    })

    it('should calculate correct items for last page with partial results', () => {
      const wrapper = mountPagination({
        currentPage: 11,
        totalPages: 11,
        perPage: 10,
        totalItems: 105,
      })

      expect(wrapper.text()).toContain('101')
      expect(wrapper.text()).toContain('105')
    })
  })

  describe('Button States', () => {
    it('should disable previous button on first page', () => {
      const wrapper = mountPagination({ currentPage: 1 })

      const prevButton = wrapper.findAll('button')[0]
      expect(prevButton.attributes('disabled')).toBeDefined()
    })

    it('should enable previous button on page > 1', () => {
      const wrapper = mountPagination({ currentPage: 2 })

      const prevButton = wrapper.findAll('button')[0]
      expect(prevButton.attributes('disabled')).toBeUndefined()
    })

    it('should disable next button on last page', () => {
      const wrapper = mountPagination({ currentPage: 10, totalPages: 10 })

      const buttons = wrapper.findAll('button')
      const nextButton = buttons[buttons.length - 1]
      expect(nextButton.attributes('disabled')).toBeDefined()
    })

    it('should enable next button when not on last page', () => {
      const wrapper = mountPagination({ currentPage: 5, totalPages: 10 })

      const buttons = wrapper.findAll('button')
      const nextButton = buttons[buttons.length - 1]
      expect(nextButton.attributes('disabled')).toBeUndefined()
    })
  })

  describe('Page Navigation', () => {
    it('should emit page-change when clicking next', async () => {
      const wrapper = mountPagination({ currentPage: 1 })

      const buttons = wrapper.findAll('button')
      const nextButton = buttons[buttons.length - 1]
      await nextButton.trigger('click')

      expect(wrapper.emitted('page-change')).toBeTruthy()
      expect(wrapper.emitted('page-change')![0]).toEqual([2])
    })

    it('should emit page-change when clicking previous', async () => {
      const wrapper = mountPagination({ currentPage: 5 })

      const prevButton = wrapper.findAll('button')[0]
      await prevButton.trigger('click')

      expect(wrapper.emitted('page-change')).toBeTruthy()
      expect(wrapper.emitted('page-change')![0]).toEqual([4])
    })

    it('should emit page-change when clicking page number', async () => {
      const wrapper = mountPagination({ currentPage: 1, totalPages: 5 })

      // Find a page number button (not prev/next)
      const pageButtons = wrapper.findAll('button').filter(btn => {
        const text = btn.text()
        return /^\d+$/.test(text)
      })

      if (pageButtons.length > 1) {
        await pageButtons[1].trigger('click')
        expect(wrapper.emitted('page-change')).toBeTruthy()
      }
    })

    it('should not emit when clicking current page', async () => {
      const wrapper = mountPagination({ currentPage: 1, totalPages: 5 })

      // Find current page button
      const pageButtons = wrapper.findAll('button').filter(btn => btn.text() === '1')

      if (pageButtons.length > 0) {
        await pageButtons[0].trigger('click')
        // Should not emit for same page
        const emitted = wrapper.emitted('page-change')
        expect(emitted === undefined || emitted.length === 0).toBe(true)
      }
    })

    it('should not emit when clicking ellipsis', async () => {
      const wrapper = mountPagination({ currentPage: 5, totalPages: 20 })

      // Ellipsis should not be clickable
      const ellipsis = wrapper.findAll('span').filter(s => s.text() === '...')

      if (ellipsis.length > 0) {
        await ellipsis[0].trigger('click')
        // Should not emit anything
        expect(wrapper.emitted('page-change')).toBeFalsy()
      }
    })
  })

  describe('Page Number Display Logic', () => {
    it('should show all pages when total <= 7', () => {
      const wrapper = mountPagination({ totalPages: 7 })

      for (let i = 1; i <= 7; i++) {
        expect(wrapper.text()).toContain(String(i))
      }
      expect(wrapper.text()).not.toContain('...')
    })

    it('should show correct pages when current is near start', () => {
      const wrapper = mountPagination({ currentPage: 2, totalPages: 10 })

      expect(wrapper.text()).toContain('1')
      expect(wrapper.text()).toContain('2')
      expect(wrapper.text()).toContain('3')
      expect(wrapper.text()).toContain('10')
    })

    it('should show correct pages when current is in middle', () => {
      const wrapper = mountPagination({ currentPage: 5, totalPages: 10 })

      expect(wrapper.text()).toContain('1')
      expect(wrapper.text()).toContain('4')
      expect(wrapper.text()).toContain('5')
      expect(wrapper.text()).toContain('6')
      expect(wrapper.text()).toContain('10')
    })

    it('should show correct pages when current is near end', () => {
      const wrapper = mountPagination({ currentPage: 9, totalPages: 10 })

      expect(wrapper.text()).toContain('1')
      expect(wrapper.text()).toContain('8')
      expect(wrapper.text()).toContain('9')
      expect(wrapper.text()).toContain('10')
    })
  })

  describe('Edge Cases', () => {
    it('should handle single page', () => {
      const wrapper = mountPagination({
        currentPage: 1,
        totalPages: 1,
        totalItems: 5,
        perPage: 10,
      })

      expect(wrapper.text()).toContain('Showing 1 to 5 of 5')

      // Both buttons should be disabled
      const buttons = wrapper.findAll('button')
      expect(buttons[0].attributes('disabled')).toBeDefined()
      expect(buttons[buttons.length - 1].attributes('disabled')).toBeDefined()
    })

    it('should handle zero items', () => {
      const wrapper = mountPagination({
        currentPage: 1,
        totalPages: 0,
        totalItems: 0,
        perPage: 10,
      })

      expect(wrapper.exists()).toBe(true)
    })
  })
})
