/**
 * Unit tests for DataTable component using Vitest and Vue Test Utils.
 * Covers rendering, selection, loading, and value formatting.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DataTable from '@/components/DataTable.vue'

const mockModel: any = {
  app: 'blog',
  name: 'Post',
  model_name: 'Post',
  table: 'blog_post',
  verbose_name: 'Post',
  verbose_name_plural: 'Posts',
  list_display: ['id', 'title', 'is_published'],
  list_filter: [],
  search_fields: ['title'],
  fields: [
    { name: 'id', type: 'integer', label: 'ID' },
    { name: 'title', type: 'string', label: 'Title' },
    { name: 'is_published', type: 'boolean', label: 'Published' },
  ],
  permissions: { view: true, add: true, change: true, delete: true },
}

const mockInstances = [
  { id: 1, title: 'First Post', is_published: true },
  { id: 2, title: 'Second Post', is_published: false },
]

function mountDataTable(props = {}) {
  return mount(DataTable, {
    props: {
      model: mockModel,
      instances: mockInstances,
      loading: false,
      ...props,
    },
    global: {
      plugins: [createPinia()],
    },
  })
}

describe('DataTable Component', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  describe('Rendering', () => {
    it('renders headers based on list_display', () => {
      const wrapper = mountDataTable()
      const headers = wrapper.findAll('th')
      // 3 data columns
      expect(headers.length).toBe(3)
      expect(headers[1].text()).toBe('Title')
    })

    it('renders data rows', () => {
      const wrapper = mountDataTable()
      const rows = wrapper.findAll('tbody tr')
      expect(rows).toHaveLength(2)
      expect(wrapper.text()).toContain('First Post')
      expect(wrapper.text()).toContain('Yes') // Boolean formatting
      expect(wrapper.text()).toContain('No')  // Boolean formatting
    })

    it('shows loading spinner when loading is true', () => {
      const wrapper = mountDataTable({ loading: true })
      expect(wrapper.find('svg.animate-spin').exists()).toBe(true)
    })

    it('shows empty state message when no instances', () => {
      const wrapper = mountDataTable({ instances: [] })
      expect(wrapper.text()).toContain('No items found')
    })
  })

  describe('Interactions', () => {
    it('emits row-click when a row is clicked', async () => {
      const wrapper = mountDataTable()
      await wrapper.find('tbody tr').trigger('click')

      expect(wrapper.emitted('row-click')).toBeTruthy()
      expect(wrapper.emitted('row-click')![0]).toEqual([mockInstances[0]])
    })

    it('emits selection-change when checkboxes are toggled', async () => {
      const wrapper = mountDataTable({ selectable: true, selectedIds: [] })

      // Click header checkbox (Toggle All)
      // Must use 'change' for checkboxes to trigger correctly in this component
      await wrapper.find('thead input[type="checkbox"]').trigger('change')
      expect(wrapper.emitted('selection-change')).toBeTruthy()
      expect(wrapper.emitted('selection-change')![0]).toEqual([[1, 2]])

      // Click row checkbox
      await wrapper.findAll('tbody input[type="checkbox"]')[0].trigger('change')
      expect(wrapper.emitted('selection-change')![1]).toEqual([[1]])
    })
  })
})
