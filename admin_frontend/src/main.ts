import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { watch } from 'vue'
import App from './App.vue'
import router from './router'
import './style.css'
import { loadExtensions } from '@/plugins/extensionLoader'

// Create Vue app
const app = createApp(App)
const pinia = createPinia()

// Install plugins
app.use(pinia)
app.use(router)

// Notify extensions on every navigation
router.afterEach((to) => {
  const params: Record<string, string> = {}
  for (const [k, v] of Object.entries(to.params)) {
    params[k] = Array.isArray(v) ? v[0] : v
  }
  window.__adminRegistry?.notifyRoute(to.path, params)
})

// Global error handler
app.config.errorHandler = (err, instance, info) => {
  console.error('Global error:', err)
  console.error('Component:', instance)
  console.error('Info:', info)
}

// Mount app
app.mount('#app')

// Wire Pinia store → extension registry so drop-ins get object/list data for free.
// Must run after mount so Pinia stores are initialised.
import('@/stores/admin').then(({ useAdminStore }) => {
  const adminStore = useAdminStore()

  // Detail page: push currentInstance changes to extensions
  watch(
    () => adminStore.currentInstance,
    (instance) => {
      const params: Record<string, string> = {}
      for (const [k, v] of Object.entries(router.currentRoute.value.params)) {
        params[k] = Array.isArray(v) ? v[0] : v
      }
      window.__adminRegistry?.notifyObject(
        instance as Record<string, any> | null,
        adminStore.currentModel as Record<string, any> | null,
        params
      )
    }
  )

  // List page: push instances changes to extensions
  watch(
    () => adminStore.instances,
    (items) => {
      const params: Record<string, string> = {}
      for (const [k, v] of Object.entries(router.currentRoute.value.params)) {
        params[k] = Array.isArray(v) ? v[0] : v
      }
      window.__adminRegistry?.notifyList(
        items as Record<string, any>[],
        adminStore.currentModel as Record<string, any> | null,
        params
      )
    }
  )
})

// Load drop-in extensions from installed apps (after mount so the DOM is ready).
// Once all extensions are registered, replay the current store state so hooks
// fire even when the page was hard-refreshed while already on a model page.
loadExtensions().then(() => {
  import('@/stores/admin').then(({ useAdminStore }) => {
    const adminStore = useAdminStore()
    const params: Record<string, string> = {}
    for (const [k, v] of Object.entries(router.currentRoute.value.params)) {
      params[k] = Array.isArray(v) ? v[0] : v
    }

    // Replay current route
    window.__adminRegistry?.notifyRoute(router.currentRoute.value.path, params)

    // Replay detail object if one is already loaded
    if (adminStore.currentInstance) {
      window.__adminRegistry?.notifyObject(
        adminStore.currentInstance as Record<string, any>,
        adminStore.currentModel as Record<string, any> | null,
        params
      )
    }

    // Replay list if rows are already loaded
    if (adminStore.instances.length > 0) {
      window.__adminRegistry?.notifyList(
        adminStore.instances as Record<string, any>[],
        adminStore.currentModel as Record<string, any> | null,
        params
      )
    }
  })
})
