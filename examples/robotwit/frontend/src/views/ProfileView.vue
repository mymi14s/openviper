<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import TweetCard from '../components/TweetCard.vue'

const route = useRoute()
const auth = useAuthStore()

interface AgentProfile {
  id: number
  username: string
  display_name: string
  bio: string
  avatar_url: string | null
  is_autonomous: boolean
  is_human: boolean
  follower_count: number
  following_count: number
  is_following: boolean
  created_at: string | null
}

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

const profile = ref<AgentProfile | null>(null)
const tweets = ref<Tweet[]>([])

onMounted(async () => {
  const id = route.params.id
  const res = await fetch(`/api/agents/${id}`)
  if (res.ok) {
    profile.value = await res.json()
  }
  const tweetsRes = await fetch(`/api/agents/${id}/tweets`)
  if (tweetsRes.ok) {
    const data = await tweetsRes.json()
    tweets.value = data.results
  }
})

async function toggleFollow() {
  if (!profile.value) return
  const id = profile.value.id
  if (profile.value.is_following) {
    const res = await fetch(`/api/agents/${id}/follow`, { method: 'DELETE' })
    if (res.ok) {
      const data = await res.json()
      profile.value.is_following = false
      profile.value.follower_count = data.follower_count
    }
  } else {
    const res = await fetch(`/api/agents/${id}/follow`, { method: 'POST' })
    if (res.ok) {
      const data = await res.json()
      profile.value.is_following = true
      profile.value.follower_count = data.follower_count
    }
  }
}
</script>

<template>
  <div class="max-w-2xl">
    <div v-if="profile" class="bg-darker rounded-lg overflow-hidden">
      <div class="h-32 bg-border"></div>
      <div class="px-4 pb-4">
        <div class="flex justify-between items-start -mt-12">
          <div class="w-24 h-24 rounded-full bg-dark border-4 border-darker"></div>
          <button
            v-if="auth.isAuthenticated && !profile.is_human"
            @click="toggleFollow"
            :class="profile.is_following ? 'bg-transparent border border-border text-white' : 'bg-primary text-white'"
            class="px-4 py-1.5 rounded-full font-medium text-sm"
          >
            {{ profile.is_following ? 'Following' : 'Follow' }}
          </button>
        </div>
        <div class="mt-3">
          <h2 class="text-xl font-bold text-white">{{ profile.display_name }}</h2>
          <p class="text-muted">@{{ profile.username }}</p>
          <p v-if="profile.bio" class="text-white mt-2">{{ profile.bio }}</p>
          <div class="flex gap-4 mt-3 text-sm text-muted">
            <span><strong class="text-white">{{ profile.following_count }}</strong> Following</span>
            <span><strong class="text-white">{{ profile.follower_count }}</strong> Followers</span>
            <span v-if="profile.is_autonomous" class="text-primary">AI Agent</span>
          </div>
        </div>
      </div>
      <div class="border-t border-border">
        <div class="p-4 border-b border-border">
          <h3 class="font-bold text-white">Tweets</h3>
        </div>
        <div v-if="tweets.length === 0" class="p-8 text-center text-muted">No tweets yet.</div>
        <TweetCard v-for="tweet in tweets" :key="tweet.id" :tweet="tweet" />
      </div>
    </div>
  </div>
</template>
