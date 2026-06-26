<script setup lang="ts">
import { onMounted } from 'vue'
import { useTimelineStore } from '../stores/timeline'
import TweetCard from '../components/TweetCard.vue'
import TrendingSidebar from '../components/TrendingSidebar.vue'

const timeline = useTimelineStore()

onMounted(async () => {
  timeline.reset()
  await timeline.fetchExplore()
})
</script>

<template>
  <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
    <div class="lg:col-span-2">
      <div class="bg-darker rounded-lg overflow-hidden">
        <div class="p-4 border-b border-border">
          <h2 class="font-bold text-white text-lg">Explore</h2>
        </div>
        <div v-if="timeline.tweets.length === 0 && !timeline.loading" class="p-8 text-center text-muted">
          No tweets to explore.
        </div>
        <TweetCard v-for="tweet in timeline.tweets" :key="tweet.id" :tweet="tweet" />
      </div>
    </div>
    <div class="hidden lg:block">
      <TrendingSidebar />
    </div>
  </div>
</template>