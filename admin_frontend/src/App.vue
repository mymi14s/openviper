<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'
import { useAdminStore } from '@/stores/admin'
import Sidebar from '@/components/Sidebar.vue'
import Header from '@/components/Header.vue'
import AlertModal from '@/components/AlertModal.vue'

const route = useRoute()
const authStore = useAuthStore()
const themeStore = useThemeStore()
const adminStore = useAdminStore()

const showLayout = computed(() => {
  return authStore.isAuthenticated && route.name !== 'login'
})

// Close sidebar when navigating on mobile
watch(() => route.path, () => {
  adminStore.closeSidebar()
})

async function handleRefresh() {
  await adminStore.clearCache()
  // Optional: visually show success or just reload
  window.location.reload()
}

onMounted(async () => {
  themeStore.init()
  if (authStore.isAuthenticated) {
    await adminStore.fetchModels()
  }
  await adminStore.fetchConfig()
  document.title = adminStore.config.admin_title
})

// Fetch models when user logs in without requiring a refresh
watch(() => authStore.isAuthenticated, async (isAuth) => {
  if (isAuth) {
    await adminStore.fetchModels()
    await adminStore.fetchConfig()
  }
})
</script>

<template>
  <div class="min-h-screen bg-gray-50 dark:bg-gray-900">
    <!-- Login page - no layout -->
    <template v-if="!showLayout">
      <router-view />
    </template>

    <!-- Main layout with sidebar -->
    <template v-else>
      <div class="flex h-screen overflow-hidden relative">
        <!-- Sidebar overlay (mobile only) -->
        <transition name="fade">
          <div
            v-if="adminStore.isSidebarOpen"
            @click="adminStore.closeSidebar"
            class="fixed inset-0 bg-gray-900/50 z-40 lg:hidden backdrop-blur-sm"
          ></div>
        </transition>

        <!-- Sidebar -->
        <Sidebar :class="[
          'fixed inset-y-0 left-0 z-50 lg:static lg:block transform transition-transform duration-300 ease-in-out',
          adminStore.isSidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
        ]" />

        <!-- Main content area -->
        <div class="flex flex-col flex-1 overflow-hidden w-full">
          <!-- Header -->
          <Header />

          <!-- Page content -->
          <main class="flex-1 overflow-y-auto p-4 md:p-6">
            <router-view v-slot="{ Component, route: routerRoute }">
              <component :is="Component" :key="routerRoute.fullPath" />
            </router-view>
          </main>
        </div>

        <!-- Floating Refresh Button -->
        <button
          @click="handleRefresh"
          class="fixed bottom-6 right-6 p-3 bg-primary-600 hover:bg-primary-700 text-white rounded-full shadow-lg hover:shadow-xl transition-all duration-200 z-50 group active:scale-95"
          title="Clear Cache & Reload"
        >
          <svg
            class="w-6 h-6 group-hover:rotate-180 transition-transform duration-500"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
        </button>
      </div>
    </template>
  </div>

  <!-- Global alert modal, rendered outside the layout tree -->
  <AlertModal />
</template>

<style>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
