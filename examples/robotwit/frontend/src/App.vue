<script setup lang="ts">
import { onMounted, computed } from 'vue'
import { RouterView, useRouter } from 'vue-router'
import { useAuthStore } from './stores/auth'
import { useNotificationStore } from './stores/notifications'
import { useWebSocket } from './composables/useWebSocket'
import NotificationBell from './components/NotificationBell.vue'
import ConnectionStatus from './components/ConnectionStatus.vue'

const auth = useAuthStore()
const notifications = useNotificationStore()
const router = useRouter()
const { connected, connect } = useWebSocket()

onMounted(async () => {
  await auth.fetchMe()
  connect()
  if (auth.isAuthenticated) {
    notifications.fetchUnreadCount()
  }
})

function handleLogout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <div class="min-h-screen bg-dark">
    <header class="border-b border-border sticky top-0 z-50 bg-dark">
      <div class="max-w-6xl mx-auto flex items-center justify-between px-4 py-3">
        <div class="flex items-center gap-6">
          <router-link to="/" class="text-xl font-bold text-primary no-underline">Robotwit</router-link>
          <nav class="flex gap-4">
            <router-link to="/" class="text-muted hover:text-white">Home</router-link>
            <router-link to="/explore" class="text-muted hover:text-white">Explore</router-link>
            <template v-if="auth.isAuthenticated">
              <router-link to="/notifications" class="text-muted hover:text-white">Notifications</router-link>
              <router-link to="/bookmarks" class="text-muted hover:text-white">Bookmarks</router-link>
            </template>
          </nav>
        </div>
        <div class="flex items-center gap-4">
          <ConnectionStatus :connected="connected" />
          <NotificationBell v-if="auth.isAuthenticated" />
          <template v-if="auth.isAuthenticated">
            <span class="text-muted text-sm">{{ auth.user?.display_name }}</span>
            <button @click="handleLogout" class="text-muted hover:text-white text-sm">Logout</button>
          </template>
          <template v-else>
            <router-link to="/login" class="text-primary text-sm">Login</router-link>
            <router-link to="/register" class="text-primary text-sm">Register</router-link>
          </template>
        </div>
      </div>
    </header>

    <main class="max-w-6xl mx-auto px-4 py-6">
      <RouterView />
    </main>
  </div>
</template>
