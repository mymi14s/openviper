<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import TweetCard from '../components/TweetCard.vue'

const route = useRoute()

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

const thread = ref<Tweet[]>([])

onMounted(async () => {
  const id = route.params.id
  const res = await fetch(`/api/tweets/${id}/thread`)
  if (res.ok) {
    const data = await res.json()
    thread.value = data.thread
  }
})
</script>

<template>
  <div class="max-w-2xl">
    <div class="bg-darker rounded-lg overflow-hidden">
      <div class="p-4 border-b border-border">
        <h2 class="font-bold text-white text-lg">Thread</h2>
      </div>
      <div v-if="thread.length === 0" class="p-8 text-center text-muted">Loading...</div>
      <TweetCard v-for="tweet in thread" :key="tweet.id" :tweet="tweet" />
    </div>
  </div>
</template>
