# Vue.js 3 Best Practices

## 1. Use the Composition API

Prefer the Composition API for better code organization, especially in medium to large applications.

```vue
<script setup>
import { ref, computed } from 'vue'

const count = ref(0)

const doubledCount = computed(() => count.value * 2)

function increment() {
  count.value++
}
</script>
```

Use `<script setup>` because it is cleaner, shorter, and recommended for Vue 3 projects.

---

## 2. Keep Components Small and Focused

Each component should have one clear responsibility.

Good component examples:

```text
UserCard.vue
UserAvatar.vue
UserProfileForm.vue
SubmitButton.vue
```

Avoid creating large components that handle too many unrelated tasks.

---

## 3. Use Props for Parent-to-Child Communication

Pass data from a parent component to a child component using props.

```vue
<script setup>
defineProps({
  title: {
    type: String,
    required: true
  }
})
</script>

<template>
  <h1>{{ title }}</h1>
</template>
```

Use clear prop names and define expected types.

---

## 4. Use Emits for Child-to-Parent Communication

Use events when a child component needs to notify a parent component.

```vue
<script setup>
const emit = defineEmits(['submit'])

function handleClick() {
  emit('submit')
}
</script>

<template>
  <button @click="handleClick">Submit</button>
</template>
```

Avoid directly modifying parent state inside child components.

---

## 5. Avoid Mutating Props Directly

Props should be treated as read-only.

Bad:

```js
props.user.name = 'New Name'
```

Better:

```js
const localUser = ref({ ...props.user })
```

Or emit an event to request the parent update the data.

---

## 6. Use `computed` for Derived State

Use `computed` when a value depends on other reactive values.

```js
const fullName = computed(() => `${firstName.value} ${lastName.value}`)
```

Avoid using methods or watchers for simple derived values.

---

## 7. Use `watch` Only When Needed

Use `watch` for side effects, such as API calls, local storage updates, or reacting to route changes.

```js
watch(searchQuery, async (newValue) => {
  await fetchResults(newValue)
})
```

Do not use `watch` when `computed` is enough.

---

## 8. Organize Reusable Logic into Composables

Move reusable logic into composables.

```js
// composables/useCounter.js
import { ref } from 'vue'

export function useCounter() {
  const count = ref(0)

  function increment() {
    count.value++
  }

  return {
    count,
    increment
  }
}
```

Then use it in a component:

```vue
<script setup>
import { useCounter } from '@/composables/useCounter'

const { count, increment } = useCounter()
</script>
```

---

## 9. Use Pinia for State Management

For shared state across multiple components, use Pinia instead of manually passing props through many levels.

```js
// stores/userStore.js
import { defineStore } from 'pinia'

export const useUserStore = defineStore('user', {
  state: () => ({
    user: null
  }),

  actions: {
    setUser(user) {
      this.user = user
    }
  }
})
```

Use local component state for simple UI state, and Pinia for global application state.

---

## 10. Use Vue Router Correctly

Keep route definitions clean and organized.

```js
const routes = [
  {
    path: '/',
    name: 'Home',
    component: () => import('@/views/HomeView.vue')
  },
  {
    path: '/profile/:id',
    name: 'Profile',
    component: () => import('@/views/ProfileView.vue')
  }
]
```

Use lazy loading for route components to improve performance.

---

## 11. Use Slots for Flexible Components

Slots make components reusable and customizable.

```vue
<template>
  <div class="card">
    <slot />
  </div>
</template>
```

Usage:

```vue
<Card>
  <h2>Profile</h2>
  <p>User information goes here.</p>
</Card>
```

Use named slots when a component has multiple content areas.

---

## 12. Validate Forms Carefully

Use controlled form state and validate user input before submitting.

```vue
<script setup>
import { ref } from 'vue'

const email = ref('')
const error = ref('')

function submitForm() {
  if (!email.value.includes('@')) {
    error.value = 'Enter a valid email address'
    return
  }

  error.value = ''
}
</script>
```

For larger projects, consider form libraries such as VeeValidate.

---

## 13. Handle Loading and Error States

Always handle loading, success, and error states when fetching data.

```vue
<script setup>
import { ref, onMounted } from 'vue'

const users = ref([])
const loading = ref(false)
const error = ref(null)

onMounted(async () => {
  loading.value = true

  try {
    const response = await fetch('/api/users')
    users.value = await response.json()
  } catch (err) {
    error.value = 'Failed to load users'
  } finally {
    loading.value = false
  }
})
</script>
```

---

## 14. Use `v-if` and `v-show` Correctly

Use `v-if` when something should be conditionally rendered.

```vue
<p v-if="isLoggedIn">Welcome back!</p>
```

Use `v-show` when something toggles often.

```vue
<div v-show="isOpen">Menu content</div>
```

`v-if` removes and recreates elements. `v-show` keeps the element in the DOM and toggles visibility.

---

## 15. Always Use `key` with `v-for`

Use a stable unique key when rendering lists.

```vue
<li v-for="user in users" :key="user.id">
  {{ user.name }}
</li>
```

Avoid using the array index as a key unless the list is static and never changes.

---

## 16. Avoid Too Much Logic in Templates

Keep templates readable.

Bad:

```vue
<p>{{ users.filter(user => user.active).map(user => user.name).join(', ') }}</p>
```

Better:

```js
const activeUserNames = computed(() =>
  users.value
    .filter(user => user.active)
    .map(user => user.name)
    .join(', ')
)
```

```vue
<p>{{ activeUserNames }}</p>
```

---

## 17. Use TypeScript for Larger Projects

TypeScript helps catch bugs early and improves maintainability.

```vue
<script setup lang="ts">
interface User {
  id: number
  name: string
}

defineProps<{
  user: User
}>()
</script>
```

Use TypeScript especially for shared models, API responses, stores, and complex components.

---

## 18. Follow a Clear Folder Structure

A common Vue 3 structure:

```text
src/
  assets/
  components/
  composables/
  layouts/
  router/
  stores/
  views/
  services/
  types/
  utils/
```

Suggested usage:

```text
components/   Reusable UI components
views/        Page-level components
composables/  Reusable Composition API logic
stores/       Pinia stores
services/     API and external service logic
types/        TypeScript interfaces and types
utils/        Helper functions
```

---

## 19. Separate API Logic from Components

Avoid putting all API calls directly inside components.

```js
// services/userService.js
export async function getUsers() {
  const response = await fetch('/api/users')

  if (!response.ok) {
    throw new Error('Failed to fetch users')
  }

  return response.json()
}
```

Then use it in your component:

```js
import { getUsers } from '@/services/userService'
```

This keeps components cleaner and easier to test.

---

## 20. Use Environment Variables

Store environment-specific values in `.env` files.

```env
VITE_API_BASE_URL=https://api.example.com
```

Use them like this:

```js
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL
```

In Vite, client-exposed environment variables must start with `VITE_`.

---

## 21. Keep Styling Consistent

Use one styling approach consistently, such as:

```text
Scoped CSS
CSS Modules
Tailwind CSS
Sass
Component library styles
```

Example with scoped CSS:

```vue
<style scoped>
.card {
  padding: 1rem;
  border-radius: 8px;
}
</style>
```

Avoid mixing too many styling systems in one project.

---

## 22. Use ESLint and Prettier

Use linting and formatting tools to keep code consistent.

Recommended tools:

```text
ESLint
Prettier
Vue ESLint Plugin
TypeScript ESLint
```

Add scripts:

```json
{
  "scripts": {
    "lint": "eslint .",
    "format": "prettier --write ."
  }
}
```

---

## 23. Use Lazy Loading for Performance

Lazy load routes and large components when possible.

```js
const DashboardView = () => import('@/views/DashboardView.vue')
```

This reduces the initial bundle size.

---

## 24. Clean Up Side Effects

Clean up intervals, event listeners, or subscriptions when a component unmounts.

```js
import { onMounted, onUnmounted } from 'vue'

function handleResize() {
  console.log(window.innerWidth)
}

onMounted(() => {
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
})
```

---

## 25. Write Tests for Important Logic

Use testing tools such as:

```text
Vitest
Vue Test Utils
Cypress
Playwright
```

Test important parts of your app:

```text
Components
Composables
Stores
Forms
API handling
Critical user flows
```

---

## 26. Use Accessibility Best Practices

Make your app usable for everyone.

Good practices:

```text
Use semantic HTML
Add labels to form inputs
Use alt text for images
Ensure keyboard navigation works
Maintain good color contrast
Use ARIA only when necessary
```

Example:

```vue
<label for="email">Email</label>
<input id="email" v-model="email" type="email" />
```

---

## 27. Avoid Overusing Global Components

Register components locally unless they are used everywhere.

Good global components:

```text
BaseButton
BaseInput
BaseModal
AppIcon
```

Avoid globally registering feature-specific components.

---

## 28. Name Components Clearly

Use multi-word component names.

Good:

```text
UserProfile.vue
ProductCard.vue
BaseButton.vue
```

Avoid:

```text
Profile.vue
Card.vue
Button.vue
```

Multi-word names reduce conflicts with native HTML elements.

---

## 29. Use Error Boundaries Where Useful

Vue provides `onErrorCaptured` to catch errors from child components.

```js
onErrorCaptured((error) => {
  console.error(error)
  return false
})
```

Use this carefully for logging or fallback UI.

---

## 30. Keep Security in Mind

Important security practices:

```text
Do not trust user input
Sanitize HTML before rendering
Avoid unnecessary use of v-html
Store tokens securely
Validate data on the backend
Use HTTPS
```

Avoid this unless the content is trusted:

```vue
<div v-html="content"></div>
```

---

# Recommended Vue 3 Stack

```text
Vue 3
Vite
Vue Router
Pinia
TypeScript
Vitest
Vue Test Utils
ESLint
Prettier
Tailwind CSS or scoped CSS
```

---

# Summary

Vue 3 best practices focus on keeping applications clean, maintainable, and scalable.

Key principles:

```text
Use Composition API
Keep components small
Use props and emits properly
Move reusable logic into composables
Use Pinia for shared state
Handle loading and errors
Use TypeScript for larger apps
Keep API logic separate
Test important features
Follow accessibility and security practices
```
