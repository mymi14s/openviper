<script setup lang="ts">
import { onMounted } from 'vue'
import { useNotificationStore } from '../stores/notifications'

const notifications = useNotificationStore()

onMounted(() => {
  notifications.fetchNotifications()
})
</script>

<template>
  <div class="max-w-2xl">
    <div class="bg-darker rounded-lg overflow-hidden">
      <div class="p-4 border-b border-border">
        <h2 class="font-bold text-white text-lg">Notifications</h2>
      </div>
      <div v-if="notifications.notifications.length === 0" class="p-8 text-center text-muted">
        No notifications yet.
      </div>
      <div
        v-for="n in notifications.notifications"
        :key="n.id"
        class="p-4 border-b border-border hover:bg-dark"
      >
        <div class="flex items-center gap-3">
          <div class="w-10 h-10 rounded-full bg-border"></div>
          <div>
            <div class="text-sm">
              <span class="font-bold text-white">{{ n.actor?.display_name }}</span>
              <span class="text-muted"> {{ n.type }}ed your tweet</span>
            </div>
            <div class="text-muted text-xs mt-1">{{ new Date(n.created_at || '').toLocaleString() }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
