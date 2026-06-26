<script setup lang="ts">
import { onMounted, ref } from 'vue'

const trending = ref<{ name: string; tweet_count: number }[]>([])

onMounted(async () => {
  const res = await fetch('/api/trending/hashtags')
  if (res.ok) {
    const data = await res.json()
    trending.value = data.results
  }
})
</script>

<template>
  <div class="bg-darker rounded-lg p-4">
    <h3 class="font-bold text-white mb-3">Trending</h3>
    <div v-if="trending.length === 0" class="text-muted text-sm">No trends yet</div>
    <div v-for="tag in trending" :key="tag.name" class="py-2">
      <router-link :to="`/hashtag/${tag.name}`" class="no-underline">
        <div class="text-primary font-medium">#{{ tag.name }}</div>
        <div class="text-muted text-xs">{{ tag.tweet_count }} tweets</div>
      </router-link>
    </div>
  </div>
</template>
