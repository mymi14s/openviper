import { ref, onUnmounted } from 'vue'
import { useTimelineStore } from '../stores/timeline'
import { useNotificationStore } from '../stores/notifications'

export function useWebSocket() {
  const connected = ref(false)
  let ws: WebSocket | null = null
  let reconnectAttempts = 0
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null

  function connect() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${window.location.host}/ws/timeline/`

    ws = new WebSocket(url)

    ws.onopen = () => {
      connected.value = true
      reconnectAttempts = 0
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        handleMessage(msg)
      } catch {
        // Ignore malformed messages
      }
    }

    ws.onclose = () => {
      connected.value = false
      scheduleReconnect()
    }

    ws.onerror = () => {
      connected.value = false
    }
  }

  function scheduleReconnect() {
    if (reconnectAttempts >= 10) return
    const delay = Math.min(1000 * 2 ** reconnectAttempts, 30000)
    reconnectAttempts++
    reconnectTimer = setTimeout(() => connect(), delay)
  }

  function handleMessage(msg: { type: string; data: any }) {
    const timeline = useTimelineStore()
    const notifications = useNotificationStore()

    switch (msg.type) {
      case 'tweet_new':
        timeline.prependTweet(msg.data)
        break
      case 'tweet_liked':
        timeline.updateTweet(msg.data.tweet_id, {
          is_liked: true,
          like_count: msg.data.like_count,
        })
        break
      case 'tweet_unliked':
        timeline.updateTweet(msg.data.tweet_id, {
          is_liked: false,
          like_count: msg.data.like_count,
        })
        break
      case 'tweet_retweeted':
        timeline.updateTweet(msg.data.tweet_id, {
          retweet_count: msg.data.retweet_count,
        })
        break
      case 'tweet_deleted':
        timeline.tweets = timeline.tweets.filter(t => t.id !== msg.data.tweet_id)
        break
      case 'notification_new':
        notifications.addNotification(msg.data)
        break
    }
  }

  function disconnect() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (ws) {
      ws.close()
      ws = null
    }
    connected.value = false
  }

  onUnmounted(() => disconnect())

  return { connected, connect, disconnect }
}
