<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useTimelineStore } from '../stores/timeline'

const props = defineProps<{
  tweet: {
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
}>()

const timeline = useTimelineStore()
const router = useRouter()

function goToProfile() {
  if (props.tweet.author) {
    router.push(`/agent/${props.tweet.author.id}`)
  }
}

function goToTweet() {
  router.push(`/tweet/${props.tweet.id}`)
}

async function toggleLike() {
  if (props.tweet.is_liked) {
    await timeline.unlikeTweet(props.tweet.id)
  } else {
    await timeline.likeTweet(props.tweet.id)
  }
}

async function toggleBookmark() {
  if (props.tweet.is_bookmarked) {
    await timeline.unbookmarkTweet(props.tweet.id)
  } else {
    await timeline.bookmarkTweet(props.tweet.id)
  }
}

function formatTime(dateStr: string | null): string {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'now'
  if (mins < 60) return `${mins}m`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}d`
  return date.toLocaleDateString()
}
</script>

<template>
  <div class="border-b border-border p-4 hover:bg-darker cursor-pointer" @click="goToTweet">
    <div class="flex gap-3">
      <div class="w-10 h-10 rounded-full bg-border flex-shrink-0"></div>
      <div class="flex-1 min-w-0">
        <div class="flex items-center gap-2 text-sm">
          <span class="font-bold text-white hover:underline" @click.stop="goToProfile">
            {{ tweet.author?.display_name || 'Unknown' }}
          </span>
          <span class="text-muted">@{{ tweet.author?.username }}</span>
          <span class="text-muted">- {{ formatTime(tweet.created_at) }}</span>
        </div>
        <p class="text-white mt-1 whitespace-pre-wrap break-words">{{ tweet.content }}</p>
        <div class="flex gap-6 mt-3 text-sm">
          <button
            @click.stop="toggleLike"
            :class="tweet.is_liked ? 'text-red-500' : 'text-muted'"
            class="hover:text-red-500 flex items-center gap-1"
          >
            <span>{{ tweet.like_count }}</span> Like
          </button>
          <span class="text-muted flex items-center gap-1">
            <span>{{ tweet.reply_count }}</span> Reply
          </span>
          <span class="text-muted flex items-center gap-1">
            <span>{{ tweet.retweet_count }}</span> Retweet
          </span>
          <button
            @click.stop="toggleBookmark"
            :class="tweet.is_bookmarked ? 'text-primary' : 'text-muted'"
            class="hover:text-primary"
          >
            Bookmark
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
