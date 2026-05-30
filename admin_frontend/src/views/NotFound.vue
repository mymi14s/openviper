<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900 px-4">
    <div class="text-center">
      <h1 class="text-9xl font-bold text-gray-200 dark:text-gray-700">404</h1>
      <p class="text-2xl font-semibold text-gray-900 dark:text-white mt-4">Page Not Found</p>
      <p class="text-gray-500 dark:text-gray-400 mt-2 mb-8">
        The page you're looking for doesn't exist or has been moved.
      </p>
      <RouterLink to="/dashboard" class="btn btn-primary">
        Go to Dashboard
      </RouterLink>
    </div>
  </div>
</template>
