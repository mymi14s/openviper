<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAdminStore } from '@/stores/admin'
import { valuesEqual } from '@/utils/compare'
import FormBuilder from '@/components/FormBuilder.vue'
import ChildTable from '@/components/ChildTable.vue'
import LoadingOverlay from '@/components/LoadingOverlay.vue'

const props = defineProps<{
  appLabel: string
  modelName: string
}>()

const router = useRouter()
const adminStore = useAdminStore()

const formData = ref<Record<string, any>>({})
const originalData = ref<Record<string, any>>({})
const errors = ref<Record<string, string>>({})
const saving = ref(false)

const isDirty = computed(() => {
  return !valuesEqual(formData.value, originalData.value)
})

const model = computed(() => adminStore.currentModel)
const loading = ref(false)

onMounted(async () => {
  loading.value = true
  try {
    await adminStore.fetchModel(props.appLabel, props.modelName)
  } finally {
    loading.value = false
  }
})

watch(model, (newModel) => {
  if (!newModel) return
  const initial: Record<string, any> = {}
  // Initialize default values for fields
  for (const field of newModel.fields) {
    if (field.default !== undefined) {
      initial[field.name] = field.default
    }
  }
  // Initialize child table arrays
  for (const ct of newModel.child_tables ?? []) {
    initial[ct.name] = []
  }
  formData.value = { ...initial }
  originalData.value = JSON.parse(JSON.stringify(initial))
}, { immediate: true })

async function handleSubmit() {
  errors.value = {}
  saving.value = true

  try {
    const instance = await adminStore.createInstance(
      props.appLabel,
      props.modelName,
      formData.value
    )

    if (instance) {
      router.push(`/${props.appLabel}/${props.modelName}/${instance.id}`)
    } else if (adminStore.error) {
      // Parse field errors if available
      errors.value = { __all__: adminStore.error }
    }
  } catch (err: any) {
    const responseErrors = err.response?.data?.errors
    if (responseErrors) {
      errors.value = responseErrors
    } else {
      errors.value = { __all__: 'An error occurred while saving.' }
    }
  } finally {
    saving.value = false
  }
}

function handleCancel() {
  router.push(`/${props.appLabel}/${props.modelName}`)
}
</script>

<template>
  <div>
    <!-- Header -->
    <div class="mb-6">
      <nav class="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 mb-2">
        <RouterLink :to="`/${appLabel}/${modelName}`" class="hover:text-gray-700 dark:hover:text-gray-200">
          {{ model?.verbose_name_plural || modelName }}
        </RouterLink>
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
        </svg>
        <span class="text-gray-900 dark:text-white">Add</span>
      </nav>
      <h1 class="text-2xl font-bold text-gray-900 dark:text-white">
        Add {{ model?.verbose_name || modelName }}
      </h1>
    </div>

    <!-- Loading state -->
    <div v-if="loading" class="flex items-center justify-center py-12">
      <svg class="animate-spin w-8 h-8 text-primary-600" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
      </svg>
    </div>

    <!-- Form -->
    <div v-else-if="model" class="max-w-5xl mx-auto">
      <div class="w-full lg:w-[70%] mx-auto space-y-6">
        <form @submit.prevent="handleSubmit" novalidate>
          <!-- Global error -->
          <div v-if="errors.__all__" class="mb-6 p-4 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-lg">
            <p class="text-sm text-red-600 dark:text-red-400">{{ errors.__all__ }}</p>
          </div>

          <div class="card p-6">
            <FormBuilder
              :model="model"
              v-model="formData"
              :errors="errors"
              :readonly-fields="model.readonly_fields"
              mode="create"
            />
          </div>

          <!-- Child Tables -->
          <div v-if="model.child_tables && model.child_tables.length > 0" class="space-y-6">
            <ChildTable
              v-for="ct in model.child_tables"
              :key="ct.name"
              :config="ct"
              v-model="formData[ct.name]"
            />
          </div>

          <!-- Actions -->
          <div class="mt-6 flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
            <button
              type="submit"
              :disabled="saving || !isDirty"
              class="btn btn-primary flex items-center justify-center gap-2 w-full sm:w-auto"
              :class="{ 'opacity-50 cursor-not-allowed': !isDirty && !saving }"
            >
              <svg v-if="saving" class="animate-spin w-5 h-5" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
              </svg>
              {{ saving ? 'Saving...' : 'Save' }}
            </button>
            <button
              type="button"
              class="btn btn-secondary w-full sm:w-auto"
              @click="handleCancel"
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>

    <LoadingOverlay :show="saving" />
  </div>
</template>
