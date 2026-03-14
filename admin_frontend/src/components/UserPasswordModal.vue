<script setup lang="ts">
import { ref, reactive, watch } from 'vue'
import { authApi } from '@/api/client'

const props = defineProps<{
  show: boolean
  userId: number | string | null
  username?: string
}>()

const emit = defineEmits<{
  'close': []
  'success': []
}>()

const form = reactive({
  newPassword: '',
  confirmPassword: '',
})

const isSubmitting = ref(false)
const error = ref('')
const fieldErrors = ref<Record<string, string>>({})

// Reset form when modal opens
watch(() => props.show, (newVal) => {
  if (newVal) {
    form.newPassword = ''
    form.confirmPassword = ''
    error.value = ''
    fieldErrors.value = {}
  }
})

async function handleSubmit() {
  if (!props.userId) return

  // Reset errors
  error.value = ''
  fieldErrors.value = {}

  // Validate
  if (!form.newPassword) {
    fieldErrors.value.newPassword = 'New password is required'
    return
  }
  if (form.newPassword.length < 8) {
    fieldErrors.value.newPassword = 'Password must be at least 8 characters'
    return
  }
  if (form.newPassword !== form.confirmPassword) {
    fieldErrors.value.confirmPassword = 'Passwords do not match'
    return
  }

  isSubmitting.value = true
  try {
    await authApi.changeUserPassword(props.userId, {
      new_password: form.newPassword,
      confirm_password: form.confirmPassword,
    })
    emit('success')
  } catch (err: any) {
    if (err.response?.data?.error) {
      error.value = err.response.data.error
    } else {
      error.value = 'Failed to change password'
    }
  } finally {
    isSubmitting.value = false
  }
}

function handleClose() {
  form.newPassword = ''
  form.confirmPassword = ''
  error.value = ''
  fieldErrors.value = {}
  emit('close')
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="show"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      @click.self="handleClose"
    >
      <div class="bg-white dark:bg-gray-800 rounded-lg shadow-xl w-full max-w-md mx-4">
        <!-- Header -->
        <div class="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h3 class="text-lg font-medium text-gray-900 dark:text-gray-100">
            Change Password
            <span v-if="username" class="text-gray-500 dark:text-gray-400 font-normal">
              for {{ username }}
            </span>
          </h3>
          <button
            @click="handleClose"
            class="text-gray-400 hover:text-gray-500 dark:hover:text-gray-300"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- Body -->
        <form @submit.prevent="handleSubmit" class="px-6 py-4 space-y-4">
          <!-- Error banner -->
          <div
            v-if="error"
            class="p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-red-700 dark:text-red-400 text-sm"
          >
            {{ error }}
          </div>

          <!-- New Password -->
          <div>
            <label for="newPassword" class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              New Password <span class="text-red-500">*</span>
            </label>
            <input
              id="newPassword"
              v-model="form.newPassword"
              type="password"
              autocomplete="new-password"
              class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500
                     border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700
                     text-gray-900 dark:text-gray-100"
              :class="{ 'border-red-500': fieldErrors.newPassword }"
            />
            <p v-if="fieldErrors.newPassword" class="mt-1 text-xs text-red-600 dark:text-red-400">
              {{ fieldErrors.newPassword }}
            </p>
          </div>

          <!-- Confirm Password -->
          <div>
            <label for="confirmPassword" class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Confirm New Password <span class="text-red-500">*</span>
            </label>
            <input
              id="confirmPassword"
              v-model="form.confirmPassword"
              type="password"
              autocomplete="new-password"
              class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500
                     border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700
                     text-gray-900 dark:text-gray-100"
              :class="{ 'border-red-500': fieldErrors.confirmPassword }"
            />
            <p v-if="fieldErrors.confirmPassword" class="mt-1 text-xs text-red-600 dark:text-red-400">
              {{ fieldErrors.confirmPassword }}
            </p>
          </div>
        </form>

        <!-- Footer -->
        <div class="flex justify-end gap-3 px-6 py-4 border-t border-gray-200 dark:border-gray-700">
          <button
            type="button"
            @click="handleClose"
            class="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 
                   bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 
                   rounded-lg transition-colors"
          >
            Cancel
          </button>
          <button
            type="submit"
            @click="handleSubmit"
            :disabled="isSubmitting"
            class="px-4 py-2 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 
                   rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <span v-if="isSubmitting">Saving...</span>
            <span v-else>Set Password</span>
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
