<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const username = ref('')
const email = ref('')
const password = ref('')
const error = ref('')

async function submit() {
  error.value = ''
  if (password.value.length < 8) {
    error.value = 'Password must be at least 8 characters'
    return
  }
  const success = await auth.register(username.value, email.value, password.value)
  if (success) {
    const loggedIn = await auth.login(username.value, password.value)
    if (loggedIn) {
      router.push('/')
    } else {
      router.push('/login')
    }
  } else {
    error.value = 'Registration failed. Username or email may be taken.'
  }
}
</script>

<template>
  <div class="max-w-md mx-auto mt-20">
    <div class="bg-darker rounded-lg p-8">
      <h2 class="text-2xl font-bold text-white mb-6">Create Account</h2>
      <div v-if="error" class="text-red-500 mb-4">{{ error }}</div>
      <div class="space-y-4">
        <div>
          <label class="text-muted text-sm block mb-1">Username</label>
          <input
            v-model="username"
            type="text"
            class="w-full bg-dark border border-border rounded px-3 py-2 text-white outline-none focus:border-primary"
          />
        </div>
        <div>
          <label class="text-muted text-sm block mb-1">Email</label>
          <input
            v-model="email"
            type="email"
            class="w-full bg-dark border border-border rounded px-3 py-2 text-white outline-none focus:border-primary"
          />
        </div>
        <div>
          <label class="text-muted text-sm block mb-1">Password (min 8 chars)</label>
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
          Register
        </button>
        <div class="text-center text-muted text-sm">
          Already have an account? <router-link to="/login">Login</router-link>
        </div>
      </div>
    </div>
  </div>
</template>