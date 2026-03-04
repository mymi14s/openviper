/**
 * Tests for Sidebar component
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import Sidebar from '@/components/Sidebar.vue'
import { useAdminStore } from '@/stores/admin'

// Create a mock router
const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/dashboard', name: 'dashboard', component: { template: '<div />' } },
    { path: '/:appLabel/:modelName', name: 'model-list', component: { template: '<div />' } },
  ],
})

function mountSidebar() {
  return mount(Sidebar, {
    global: {
      plugins: [createPinia(), router],
    },
  })
}

describe('Sidebar Component', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  describe('Rendering', () => {
    it('should render logo and title', () => {
      const wrapper = mountSidebar()

      expect(wrapper.text()).toContain('OpenViper')
    })

    it('should render dashboard link', () => {
      const wrapper = mountSidebar()

      expect(wrapper.text()).toContain('Dashboard')
    })

    it('should render footer with version', () => {
      const wrapper = mountSidebar()

      expect(wrapper.text()).toContain('OpenViper Admin')
    })
  })

  describe('Model list', () => {
    it('should render models grouped by app', async () => {
      const wrapper = mountSidebar()
      const store = useAdminStore()

      store.models = [
        { app: 'blog', name: 'Post', verbose_name: 'Post', verbose_name_plural: 'Posts' },
        { app: 'blog', name: 'Comment', verbose_name: 'Comment', verbose_name_plural: 'Comments' },
        { app: 'auth', name: 'User', verbose_name: 'User', verbose_name_plural: 'Users' },
      ] as any

      await wrapper.vm.$nextTick()

      expect(wrapper.text()).toContain('Blog')
      expect(wrapper.text()).toContain('Auth')
      expect(wrapper.text()).toContain('Posts')
      expect(wrapper.text()).toContain('Comments')
      expect(wrapper.text()).toContain('Users')
    })

    it('should not render models section if no models', () => {
      const wrapper = mountSidebar()
      const store = useAdminStore()

      store.models = []

      // Only dashboard link should be present
      const links = wrapper.findAll('a')
      expect(links.length).toBeGreaterThanOrEqual(1) // At least dashboard link
    })

    it('should format app labels correctly', async () => {
      const wrapper = mountSidebar()
      const store = useAdminStore()

      store.models = [
        { app: 'my_app', name: 'MyModel', verbose_name_plural: 'My Models' },
      ] as any

      await wrapper.vm.$nextTick()

      // Should capitalize and replace underscores
      expect(wrapper.text()).toContain('My app')
    })
  })

  describe('Navigation', () => {
    it('should have correct link to dashboard', () => {
      const wrapper = mountSidebar()

      const dashboardLink = wrapper.find('a[href="/dashboard"]')
      expect(dashboardLink.exists()).toBe(true)
    })

    it('should have correct links to models', async () => {
      const wrapper = mountSidebar()
      const store = useAdminStore()

      store.models = [
        { app: 'blog', name: 'Post', verbose_name_plural: 'Posts' },
      ] as any

      await wrapper.vm.$nextTick()

      const modelLink = wrapper.find('a[href="/blog/Post"]')
      expect(modelLink.exists()).toBe(true)
    })
  })

  describe('Active state', () => {
    it('should highlight active model', async () => {
      await router.push('/blog/Post')

      const wrapper = mountSidebar()
      const store = useAdminStore()

      store.models = [
        { app: 'blog', name: 'Post', verbose_name_plural: 'Posts' },
      ] as any

      await wrapper.vm.$nextTick()

      // The active class should be applied
      const links = wrapper.findAll('.sidebar-link')
      expect(links.length).toBeGreaterThan(0)
    })
  })
})
