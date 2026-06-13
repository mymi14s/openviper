<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useAdminStore } from '@/stores/admin'
import { useAlertsStore } from '@/stores/alerts'
import { validateRequiredFields, getChangedFields } from '@/utils/formHelpers'
import FormBuilder from '@/components/FormBuilder.vue'
import ChildTable from '@/components/ChildTable.vue'
import LoadingOverlay from '@/components/LoadingOverlay.vue'

const props = defineProps<{
  appLabel: string
  modelName: string
}>()

const adminStore = useAdminStore()
const alertsStore = useAlertsStore()

const formTopRef = ref<HTMLElement | null>(null)
const formData = ref<Record<string, unknown>>({})
const originalData = ref<Record<string, unknown>>({})
const errors = ref<Record<string, string>>({})
const loading = ref(true)
const saving = ref(false)
const showSuccess = ref(false)
let successTimer: number | undefined

const model = computed(() => adminStore.currentModel)
const instance = computed(() => adminStore.currentInstance)
const canChange = computed(
  () => model.value?.capabilities?.can_update_single ?? model.value?.permissions?.change ?? true
)
const isDirty = computed(() => Object.keys(getChangedFields(formData.value, originalData.value)).length > 0)
const isExistingRecord = computed(() => instance.value !== null && instance.value !== undefined)

function scrollToFormTop(): void {
  formTopRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

async function loadData(): Promise<void> {
  loading.value = true
  originalData.value = {}
  adminStore.clearCurrent()
  try {
    await adminStore.fetchModel(props.appLabel, props.modelName)
    try {
      await adminStore.fetchSingleInstance(props.appLabel, props.modelName)
    } catch {
      // No instance exists yet - this is valid for initial creation.
    }
    if (instance.value) {
      originalData.value = JSON.parse(JSON.stringify(instance.value))
      formData.value = { ...instance.value }
    } else {
      // Initialize form with default values from field definitions.
      const defaults: Record<string, unknown> = {}
      for (const field of model.value?.fields ?? []) {
        if (field.default !== undefined && field.default !== null) {
          defaults[field.name] = field.default
        }
      }
      formData.value = { ...defaults }
    }
  } finally {
    loading.value = false
  }
}

async function handleSubmit(): Promise<void> {
  errors.value = {}
  const fieldErrors = validateRequiredFields(model.value?.fields ?? [], formData.value)
  if (Object.keys(fieldErrors).length > 0) {
    errors.value = fieldErrors
    scrollToFormTop()
    return
  }

  saving.value = true
  try {
    if (instance.value) {
      const changedFields = getChangedFields(formData.value, originalData.value)
      if (Object.keys(changedFields).length === 0) {
        saving.value = false
        return
      }
      const updated = await adminStore.updateSingleInstance(
        props.appLabel,
        props.modelName,
        changedFields
      )
      if (updated) {
        await loadData()
        showSuccess.value = true
        successTimer = window.setTimeout(() => (showSuccess.value = false), 3000)
        scrollToFormTop()
      } else if (adminStore.error) {
        alertsStore.show({ type: 'error', title: 'Save Failed', message: adminStore.error })
      }
    } else {
      const created = await adminStore.createInstance(
        props.appLabel,
        props.modelName,
        formData.value
      )
      if (created) {
        await loadData()
        showSuccess.value = true
        successTimer = window.setTimeout(() => (showSuccess.value = false), 3000)
        scrollToFormTop()
      } else if (adminStore.error) {
        alertsStore.show({ type: 'error', title: 'Save Failed', message: adminStore.error })
      }
    }
  } catch (err: unknown) {
    const axiosErr = err as { response?: { data?: { errors?: Record<string, string>; detail?: string; __all__?: string } } }
    const responseErrors = axiosErr.response?.data?.errors
    if (responseErrors && Object.keys(responseErrors).some((k) => k !== '__all__')) {
      errors.value = responseErrors
      scrollToFormTop()
    } else {
      const msg = responseErrors?.__all__ || axiosErr.response?.data?.detail || 'An error occurred while saving.'
      alertsStore.show({ type: 'error', title: 'Save Failed', message: msg })
    }
  } finally {
    saving.value = false
  }
}

onMounted(loadData)

watch(
  () => [props.appLabel, props.modelName],
  async () => { await loadData() }
)

onUnmounted(() => {
  if (successTimer !== undefined) {
    clearTimeout(successTimer)
  }
})
</script>

<template>
  <div ref="formTopRef">
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
      <div>
        <h1 class="text-2xl font-bold text-gray-900 dark:text-white">
          {{ model?.verbose_name || modelName }}
        </h1>
      </div>
    </div>

    <div v-if="loading" class="flex items-center justify-center py-12">
      <svg class="animate-spin w-8 h-8 text-primary-600" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
      </svg>
    </div>

    <div v-else-if="model" class="max-w-4xl">
      <transition name="banner">
        <div v-if="errors.__all__" id="__all__" class="p-4 mb-6 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-lg">
          <p class="text-sm text-red-600 dark:text-red-400">{{ errors.__all__ }}</p>
        </div>
      </transition>

      <transition name="banner">
        <div v-if="showSuccess" class="p-4 mb-6 bg-green-50 dark:bg-green-900/30 border border-green-200 dark:border-green-800 rounded-lg flex items-center gap-3">
          <svg class="w-5 h-5 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
          </svg>
          <p class="text-sm text-green-600 dark:text-green-400">Changes saved successfully!</p>
        </div>
      </transition>

      <form @submit.prevent="handleSubmit" novalidate>
        <div class="card p-6">
          <FormBuilder
            :key="model?.name"
            :model="model"
            v-model="formData"
            :errors="errors"
            :readonly-fields="model.readonly_fields"
            :disabled="!canChange"
            mode="edit"
          />
        </div>

        <div v-if="model.child_tables && model.child_tables.length > 0" class="mt-6 space-y-6">
          <ChildTable
            v-for="ct in model.child_tables"
            :key="ct.name"
            :config="ct"
            v-model="formData[ct.name]"
            :disabled="!canChange"
          />
        </div>

        <div
          v-if="canChange"
          class="sticky bottom-0 z-20 mt-6 -mx-4 px-4 md:-mx-6 md:px-6 py-3 bg-white/90 dark:bg-gray-900/90 backdrop-blur border-t border-gray-200 dark:border-gray-700 flex items-center gap-4"
        >
          <button
            type="submit"
            :disabled="saving || (isExistingRecord && !isDirty)"
            class="btn btn-primary flex items-center gap-2"
            :class="{ 'opacity-50 cursor-not-allowed': isExistingRecord && !isDirty && !saving }"
          >
            <svg v-if="saving" class="animate-spin w-5 h-5" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
            </svg>
            {{ saving ? 'Saving...' : (isExistingRecord ? 'Save Changes' : 'Create') }}
          </button>
        </div>
      </form>
    </div>

    <LoadingOverlay :show="saving" />
  </div>
</template>
