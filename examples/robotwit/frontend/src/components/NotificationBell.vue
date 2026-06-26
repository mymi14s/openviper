<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useNotificationStore } from '../stores/notifications'

const notifications = useNotificationStore()
const showDropdown = ref(false)

onMounted(() => {
  notifications.fetchUnreadCount()
})

function toggleDropdown() {
  showDropdown.value = !showDropdown.value
  if (showDropdown.value && notifications.notifications.length === 0) {
    notifications.fetchNotifications()
  }
}

function markAllRead() {
  notifications.markAllRead()
}
</script>

<template>
  <div class="relative">
    <button @click="toggleDropdown" class="text-muted hover:text-white relative">
      Notifications
      <span
        v-if="notifications.unreadCount > 0"
        class="absolute -top-2 -right-2 bg-primary text-white text-xs rounded-full px-1.5"
      >
        {{ notifications.unreadCount }}
      </span>
    </button>
    <div
      v-if="showDropdown"
      class="absolute right-0 top-full mt-2 w-80 bg-darker border border-border rounded-lg shadow-xl z-50"
    >
      <div class="p-3 border-b border-border flex justify-between items-center">
        <span class="font-bold">Notifications</span>
        <button @click="markAllRead" class="text-primary text-sm">Mark all read</button>
      </div>
      <div class="max-h-96 overflow-y-auto">
        <div
          v-for="n in notifications.notifications"
          :key="n.id"
          class="p-3 border-b border-border hover:bg-dark"
        >
          <div class="text-sm">
            <span class="font-bold">{{ n.actor?.display_name }}</span>
            <span class="text-muted"> {{ n.type }}ed your tweet</span>
          </div>
          <div class="text-muted text-xs mt-1">{{ new Date(n.created_at || '').toLocaleString() }}</div>
        </div>
        <div v-if="notifications.notifications.length === 0" class="p-4 text-muted text-center">
          No notifications
        </div>
      </div>
    </div>
  </div>
</template>