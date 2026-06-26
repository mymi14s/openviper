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

const tweets = ref<Tweet[]>([])

onMounted(async () => {
  const name = route.params.name
  const res = await fetch(`/api/hashtags/${name}`)
  if (res.ok) {
    const data = await res.json()
    tweets.value = data.results
  }
})
</script>

<template>
  <div class="max-w-2xl">
    <div class="bg-darker rounded-lg overflow-hidden">
      <div class="p-4 border-b border-border">
        <h2 class="font-bold text-white text-lg">#{{ route.params.name }}</h2>
      </div>
      <div v-if="tweets.length === 0" class="p-8 text-center text-muted">No tweets with this hashtag.</div>
      <TweetCard v-for="tweet in tweets" :key="tweet.id" :tweet="tweet" />
    </div>
  </div>
</template>