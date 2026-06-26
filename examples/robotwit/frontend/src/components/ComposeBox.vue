<script setup lang="ts">
import { computed, ref } from 'vue'
import { useTimelineStore } from '../stores/timeline'
import { useAuthStore } from '../stores/auth'

const timeline = useTimelineStore()
const auth = useAuthStore()
const content = ref('')
const charCount = computed(() => content.value.length)

async function submit() {
  if (!content.value.trim() || content.value.length > 280) return
  await timeline.createTweet(content.value.trim())
  content.value = ''
}
</script>

<template>
  <div v-if="auth.isAuthenticated" class="border-b border-border p-4">
    <div class="flex gap-3">
      <div class="w-10 h-10 rounded-full bg-border flex-shrink-0"></div>
      <div class="flex-1">
        <textarea
          v-model="content"
          placeholder="What's happening?"
          class="w-full bg-transparent text-white text-lg outline-none resize-none"
          rows="2"
          maxlength="280"
        ></textarea>
        <div class="flex justify-between items-center mt-2">
          <span :class="charCount > 260 ? 'text-red-500' : 'text-muted'" class="text-sm">
            {{ 280 - charCount }}
          </span>
          <button
            @click="submit"
            :disabled="!content.trim() || charCount > 280"
            class="bg-primary text-white px-5 py-1.5 rounded-full font-medium disabled:opacity-50 hover:bg-blue-600"
          >
            Tweet
          </button>
        </div>
      </div>
    </div>
  </div>
</template>