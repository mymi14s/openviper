import { defineStore } from 'pinia'
import { ref } from 'vue'

interface Notification {
  id: number
  type: string
  actor: {
    id: number
    username: string
    display_name: string
    avatar_url: string | null
  } | null
  tweet_id: number | null
  read_at: string | null
  created_at: string | null
}

export const useNotificationStore = defineStore('notifications', () => {
  const notifications = ref<Notification[]>([])
  const unreadCount = ref(0)

  async function fetchUnreadCount() {
    const res = await fetch('/api/notifications/unread-count')
    if (res.ok) {
      const data = await res.json()
      unreadCount.value = data.count
    }
  }

  async function fetchNotifications() {
    const res = await fetch('/api/notifications?limit=30')
    if (res.ok) {
      const data = await res.json()
      notifications.value = data.results
    }
  }

  async function markAllRead() {
    await fetch('/api/notifications/mark-read', { method: 'POST' })
    unreadCount.value = 0
    notifications.value.forEach(n => { n.read_at = new Date().toISOString() })
  }

  function addNotification(notification: Notification) {
    notifications.value.unshift(notification)
    unreadCount.value++
  }

  return {
    notifications, unreadCount,
    fetchUnreadCount, fetchNotifications, markAllRead, addNotification,
  }
})
