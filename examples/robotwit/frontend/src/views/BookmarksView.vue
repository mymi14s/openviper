<script setup lang="ts">
import { ref } from 'vue'
import { useTimelineStore } from '../stores/timeline'

const timeline = useTimelineStore()

interface Tweet {
  id: number
  content: string
  author: { id: number; username: string; display_name: string; avatar_url: string | null } | null
  like_count: number
  retweet_count: number
  reply_count: number
  is_liked: boolean
  is_bookmarked: boolean
  reply_to_id: number | null
  retweet_of_id: number | null
  created_at: string | null
}

const bookmarks = ref<Tweet[]>([])

async function loadBookmarks() {
  const res = await fetch('/api/bookmarks')
  if (res.ok) {
    const data = await res.json()
    bookmarks.value = data.results
  }
}

async function toggleLike(tweet: Tweet) {
  if (tweet.is_liked) {
    await timeline.unlikeTweet(tweet.id)
    tweet.is_liked = false
    tweet.like_count = Math.max(0, tweet.like_count - 1)
  } else {
    await timeline.likeTweet(tweet.id)
    tweet.is_liked = true
    tweet.like_count += 1
  }
}

async function toggleBookmark(tweet: Tweet) {
  if (tweet.is_bookmarked) {
    await fetch(`/api/tweets/${tweet.id}/bookmark`, { method: 'DELETE' })
    tweet.is_bookmarked = false
    bookmarks.value = bookmarks.value.filter(b => b.id !== tweet.id)
  } else {
    await fetch(`/api/tweets/${tweet.id}/bookmark`, { method: 'POST' })
    tweet.is_bookmarked = true
  }
}

loadBookmarks()
</script>

<template>
  <div class="max-w-2xl">
    <div class="bg-darker rounded-lg overflow-hidden">
      <div class="p-4 border-b border-border">
        <h2 class="font-bold text-white text-lg">Bookmarks</h2>
      </div>
      <div v-if="bookmarks.length === 0" class="p-8 text-center text-muted">
        No bookmarks yet.
      </div>
      <div v-for="tweet in bookmarks" :key="tweet.id" class="border-b border-border p-4">
        <div class="flex gap-3">
          <div class="w-10 h-10 rounded-full bg-border flex-shrink-0"></div>
          <div class="flex-1">
            <div class="text-sm">
              <span class="font-bold text-white">{{ tweet.author?.display_name }}</span>
              <span class="text-muted"> @{{ tweet.author?.username }}</span>
            </div>
            <p class="text-white mt-1">{{ tweet.content }}</p>
            <div class="flex gap-6 mt-2 text-muted text-sm">
              <button @click="toggleLike(tweet)" class="flex items-center gap-1 hover:text-red-500">
                {{ tweet.is_liked ? '♥' : '♡' }} {{ tweet.like_count }}
              </button>
              <button @click="toggleBookmark(tweet)" class="flex items-center gap-1 hover:text-blue-500">
                {{ tweet.is_bookmarked ? '🔖' : '🔖' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
