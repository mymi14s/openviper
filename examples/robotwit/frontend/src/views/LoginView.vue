<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const identifier = ref('')
const password = ref('')
const error = ref('')

async function submit() {
  error.value = ''
  const success = await auth.login(identifier.value, password.value)
  if (success) {
    router.push('/')
  } else {
    error.value = 'Invalid credentials'
  }
}
</script>

<template>
  <div class="max-w-md mx-auto mt-20">
    <div class="bg-darker rounded-lg p-8">
      <h2 class="text-2xl font-bold text-white mb-6">Login</h2>
      <div v-if="error" class="text-red-500 mb-4">{{ error }}</div>
      <div class="space-y-4">
        <div>
          <label class="text-muted text-sm block mb-1">Username or Email</label>
          <input
            v-model="identifier"
            type="text"
            class="w-full bg-dark border border-border rounded px-3 py-2 text-white outline-none focus:border-primary"
          />
        </div>
        <div>
          <label class="text-muted text-sm block mb-1">Password</label>
          <input
            v-model="password"
            type="password"
            class="w-full bg-dark border border-border rounded px-3 py-2 text-white outline-none focus:border-primary"
            @keyup.enter="submit"
          />
        </div>
        <button
          @click="submit"
          class="w-full bg-primary text-white py-2 rounded font-medium hover:bg-blue-600"
        >
          Login
        </button>
        <div class="text-center text-muted text-sm">
          Don't have an account? <router-link to="/register">Register</router-link>
        </div>
      </div>
    </div>
  </div>
</template>
