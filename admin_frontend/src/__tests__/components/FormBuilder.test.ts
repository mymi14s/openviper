/**
 * Unit tests for FormBuilder component using Vitest and Vue Test Utils.
 */
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import FormBuilder from '@/components/FormBuilder.vue'

// Mock API client
vi.mock('@/api/client', () => ({
  modelsApi: {
    searchForeignKey: vi.fn().mockResolvedValue({ data: [] }),
  },
  authApi: {},
  dashboardApi: {},
  historyApi: {},
}))

const mockModel = {
  name: 'Post',
  app: 'blog',
  table: 'blog_post',
  verbose_name: 'Post',
  verbose_name_plural: 'Posts',
  list_display: ['id', 'title'],
  list_filter: [],
  search_fields: ['title'],
  ordering: ['-created_at'],
  list_per_page: 25,
  readonly_fields: [],
  actions: [],
  fields: [
    { name: 'title', type: 'string', label: 'Title', required: true, readonly: false },
    { name: 'content', type: 'textarea', label: 'Content', required: false, readonly: false },
    { name: 'is_published', type: 'boolean', label: 'Published', required: false, readonly: false },
    { name: 'category', type: 'select', label: 'Category', required: false, readonly: false, choices: [{ value: 'tech', label: 'Technology' }] },
    { name: 'author', type: 'ForeignKey', label: 'Author', required: false, readonly: false, related_model: 'auth.User' },
    { name: 'website', type: 'URLField', label: 'Website', required: false, readonly: false },
    { name: 'social', type: 'URLField', label: 'Social', required: false, readonly: true },
  ],
}

const defaultModelValue = {
  title: '',
  content: '',
  is_published: false,
  category: '',
  author: null,
  website: 'https://example.com',
  social: 'https://twitter.com/openviper',
}

describe('FormBuilder Component', () => {
  it('renders editable fields', () => {
    const wrapper = mount(FormBuilder, {
      props: {
        model: mockModel as any,
        modelValue: defaultModelValue,
      },
      global: {
        stubs: {
          ForeignKeyField: true,
        },
      },
    })

    expect(wrapper.find('input[type="text"]').exists()).toBe(true)
    expect(wrapper.find('textarea').exists()).toBe(true)
    expect(wrapper.find('input[type="checkbox"]').exists()).toBe(true)
    expect(wrapper.find('select').exists()).toBe(true)
  })

  it('updates field value and emits change', async () => {
    const wrapper = mount(FormBuilder, {
      props: {
        model: mockModel as any,
        modelValue: { ...defaultModelValue, title: 'Old Title' },
      },
    })

    const input = wrapper.find('input[type="text"]')
    await input.setValue('New Title')

    expect(wrapper.emitted('update:modelValue')).toBeTruthy()
    expect(wrapper.emitted('update:modelValue')![0][0]).toEqual({ ...defaultModelValue, title: 'New Title' })
  })

  it('handles checkbox toggling', async () => {
    const wrapper = mount(FormBuilder, {
      props: {
        model: mockModel as any,
        modelValue: { ...defaultModelValue, is_published: false },
      },
    })

    const checkbox = wrapper.find('input[type="checkbox"]')
    await checkbox.setValue(true)

    expect(wrapper.emitted('update:modelValue')![0][0]).toEqual({ ...defaultModelValue, is_published: true })
  })

  it('renders URLField as a link when readonly', () => {
    const wrapper = mount(FormBuilder, {
      props: {
        model: mockModel as any,
        modelValue: defaultModelValue,
      },
    })

    const socialLink = wrapper.find('a[href="https://twitter.com/openviper"]')
    expect(socialLink.exists()).toBe(true)
    expect(socialLink.attributes('target')).toBe('_blank')
    expect(socialLink.text()).toBe('https://twitter.com/openviper')
  })

  it('renders URLField with a link button when editable', () => {
    const wrapper = mount(FormBuilder, {
      props: {
        model: mockModel as any,
        modelValue: defaultModelValue,
      },
    })

    const websiteInput = wrapper.find('input[type="url"]')
    expect(websiteInput.exists()).toBe(true)
    expect((websiteInput.element as HTMLInputElement).value).toBe('https://example.com')

    const linkButton = wrapper.find('a[title="Open link in new tab"]')
    expect(linkButton.exists()).toBe(true)
    expect(linkButton.attributes('href')).toBe('https://example.com')
  })
})
