<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useTimelineStore } from '../stores/timeline'
import { useAuthStore } from '../stores/auth'
import { useWebSocket } from '../composables/useWebSocket'
import ComposeBox from '../components/ComposeBox.vue'
import TweetCard from '../components/TweetCard.vue'
import TrendingSidebar from '../components/TrendingSidebar.vue'

const timeline = useTimelineStore()
const auth = useAuthStore()
const { connect } = useWebSocket()
const loadingMore = ref(false)

onMounted(async () => {
  timeline.reset()
  if (auth.isAuthenticated) {
    await timeline.fetchHome()
    connect()
  } else {
    await timeline.fetchExplore()
  }
})

async function loadMore() {
  if (loadingMore.value || !timeline.hasMore) return
  loadingMore.value = true
  try {
    if (auth.isAuthenticated) {
      await timeline.fetchHome()
    } else {
      await timeline.fetchExplore()
    }
  } finally {
    loadingMore.value = false
  }
}
</script>

<template>
  <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
    <div class="lg:col-span-2">
      <div class="bg-darker rounded-lg overflow-hidden">
        <div class="p-4 border-b border-border">
          <h2 class="font-bold text-white text-lg">Home</h2>
        </div>
        <ComposeBox v-if="auth.isAuthenticated" />
        <div v-if="timeline.tweets.length === 0 && !timeline.loading" class="p-8 text-center text-muted">
          No tweets yet. Be the first!
        </div>
        <TweetCard v-for="tweet in timeline.tweets" :key="tweet.id" :tweet="tweet" />
        <div v-if="timeline.hasMore" class="p-4 text-center">
          <button
            @click="loadMore"
            :disabled="loadingMore"
            class="text-primary hover:underline disabled:opacity-50"
          >
            {{ loadingMore ? 'Loading...' : 'Load more' }}
          </button>
        </div>
      </div>
    </div>
    <div class="hidden lg:block">
      <TrendingSidebar />
    </div>
  </div>
</template>