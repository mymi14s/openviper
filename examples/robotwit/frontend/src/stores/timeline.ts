import { defineStore } from 'pinia'
import { ref } from 'vue'

interface Tweet {
  id: number
  content: string
  author: {
    id: number
    username: string
    display_name: string
    avatar_url: string | null
  } | null
  like_count: number
  retweet_count: number
  reply_count: number
  is_liked: boolean
  is_bookmarked: boolean
  reply_to_id: number | null
  retweet_of_id: number | null
  created_at: string | null
}

export const useTimelineStore = defineStore('timeline', () => {
  const tweets = ref<Tweet[]>([])
  const nextCursor = ref<string | null>(null)
  const loading = ref(false)
  const hasMore = ref(true)

  async function fetchHome() {
    if (loading.value) return
    loading.value = true
    try {
      const url = nextCursor.value
        ? `/api/timeline/home?cursor=${nextCursor.value}`
        : '/api/timeline/home'
      const res = await fetch(url)
      if (res.ok) {
        const data = await res.json()
        tweets.value.push(...data.results)
        nextCursor.value = data.next_cursor
        hasMore.value = data.next_cursor !== null
      }
    } finally {
      loading.value = false
    }
  }

  async function fetchExplore() {
    if (loading.value) return
    loading.value = true
    try {
      const url = nextCursor.value
        ? `/api/timeline/explore?cursor=${nextCursor.value}`
        : '/api/timeline/explore'
      const res = await fetch(url)
      if (res.ok) {
        const data = await res.json()
        tweets.value.push(...data.results)
        nextCursor.value = data.next_cursor
        hasMore.value = data.next_cursor !== null
      }
    } finally {
      loading.value = false
    }
  }

  function reset() {
    tweets.value = []
    nextCursor.value = null
    hasMore.value = true
  }

  function prependTweet(tweet: Tweet) {
    tweets.value.unshift(tweet)
  }

  function updateTweet(tweetId: number, updates: Partial<Tweet>) {
    const idx = tweets.value.findIndex(t => t.id === tweetId)
    if (idx !== -1) {
      tweets.value[idx] = { ...tweets.value[idx], ...updates }
    }
  }

  async function likeTweet(tweetId: number) {
    const res = await fetch(`/api/tweets/${tweetId}/like`, { method: 'POST' })
    if (res.ok) {
      const data = await res.json()
      updateTweet(tweetId, { is_liked: true, like_count: data.like_count })
    }
  }

  async function unlikeTweet(tweetId: number) {
    const res = await fetch(`/api/tweets/${tweetId}/like`, { method: 'DELETE' })
    if (res.ok) {
      const data = await res.json()
      updateTweet(tweetId, { is_liked: false, like_count: data.like_count })
    }
  }

  async function bookmarkTweet(tweetId: number) {
    await fetch(`/api/tweets/${tweetId}/bookmark`, { method: 'POST' })
    updateTweet(tweetId, { is_bookmarked: true })
  }

  async function unbookmarkTweet(tweetId: number) {
    await fetch(`/api/tweets/${tweetId}/bookmark`, { method: 'DELETE' })
    updateTweet(tweetId, { is_bookmarked: false })
  }

  async function createTweet(content: string, replyToId?: number) {
    const res = await fetch('/api/tweets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, reply_to_id: replyToId }),
    })
    if (res.ok) {
      const tweet = await res.json()
      prependTweet(tweet)
      return tweet
    }
    return null
  }

  return {
    tweets, nextCursor, loading, hasMore,
    fetchHome, fetchExplore, reset,
    prependTweet, updateTweet,
    likeTweet, unlikeTweet, bookmarkTweet, unbookmarkTweet, createTweet,
  }
})