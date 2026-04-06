<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAdminStore } from '@/stores/admin'
import { useAlertsStore } from '@/stores/alerts'
import { valuesEqual } from '@/utils/compare'
import FormBuilder from '@/components/FormBuilder.vue'
import UserPasswordModal from '@/components/UserPasswordModal.vue'
import InstanceSidebar from '@/components/InstanceSidebar.vue'
import ChildTable from '@/components/ChildTable.vue'
import LoadingOverlay from '@/components/LoadingOverlay.vue'

const sidebarRef = ref<InstanceType<typeof InstanceSidebar> | null>(null)
const formTopRef = ref<HTMLElement | null>(null)

const props = defineProps<{
  appLabel: string
  modelName: string
  id: string
}>()

const router = useRouter()
const adminStore = useAdminStore()
const alertsStore = useAlertsStore()

const formData = ref<Record<string, any>>({})
const originalData = ref<Record<string, any>>({})
const errors = ref<Record<string, string>>({})
const saving = ref(false)
const showSuccess = ref(false)
const showDeleteConfirm = ref(false)
const showPasswordModal = ref(false)

const isDirty = computed(() => {
  if (!instance.value) return false
  return Object.keys(getChangedFields()).length > 0
})

/**
 * Get only the fields that have changed from original data.
 */
function getChangedFields(): Record<string, any> {
  const changes: Record<string, any> = {}

  for (const [key, value] of Object.entries(formData.value)) {
    // Skip id field
    if (key === 'id') continue

    const originalValue = originalData.value[key]

    if (!valuesEqual(value, originalValue)) {
      changes[key] = value
    }
  }

  return changes
}

const model = computed(() => adminStore.currentModel)
const instance = computed(() => adminStore.currentInstance)
const loading = ref(false)

const canChange = computed(() => model.value?.permissions?.change ?? true)
const canDelete = computed(() => model.value?.permissions?.delete ?? true)
const canAdd = computed(() => model.value?.permissions?.add ?? true)

// Check if this is a User model
const isUserModel = computed(() => {
  const modelStr = `${props.appLabel}.${props.modelName}`
  return (
    modelStr === adminStore.config.auth_user_model ||
    modelStr === adminStore.config.user_model ||
    (props.appLabel === 'auth' && props.modelName.toLowerCase() === 'user')
  )
})

async function loadData() {
  loading.value = true
  originalData.value = {}
  adminStore.clearCurrent()

  try {
    await adminStore.fetchModel(props.appLabel, props.modelName)
    await adminStore.fetchInstance(props.appLabel, props.modelName, props.id)

    if (instance.value) {
      originalData.value = JSON.parse(JSON.stringify(instance.value))
      formData.value = { ...instance.value }
    }
  } finally {
    loading.value = false
  }
}

onMounted(loadData)

watch(
  () => [props.appLabel, props.modelName, props.id],
  async () => { await loadData() }
)

function scrollToFormTop() {
  formTopRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function scrollToFirstError(errs: Record<string, string>) {
  // Collect field keys in model field order, then check for __all__ fallback
  const fieldOrder = model.value?.fields?.map((f) => f.name) ?? []
  const firstField = fieldOrder.find((name) => errs[name])
  const targetId = firstField ?? (errs.__all__ ? '__all__' : null)
  if (targetId) {
    const el = document.getElementById(targetId)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      return
    }
  }
  scrollToFormTop()
}

async function handleSubmit() {
  errors.value = {}
  saving.value = true

  try {
    // Only send fields that have changed
    const changedFields = getChangedFields()

    // If nothing changed, just return success without API call
    if (Object.keys(changedFields).length === 0) {
      saving.value = false
      return
    }

    const updated = await adminStore.updateInstance(
      props.appLabel,
      props.modelName,
      props.id,
      changedFields
    )

    if (updated) {
      // Reload full instance data including child tables
      await loadData()
      showSuccess.value = true
      setTimeout(() => (showSuccess.value = false), 3000)
      // Refresh sidebar history after successful save
      sidebarRef.value?.fetchHistory()
      scrollToFormTop()
    } else if (adminStore.error) {
      alertsStore.show({ type: 'error', title: 'Save Failed', message: adminStore.error })
    }
  } catch (err: any) {
    const responseErrors = err.response?.data?.errors
    if (responseErrors && Object.keys(responseErrors).some((k) => k !== '__all__')) {
      errors.value = responseErrors
      scrollToFirstError(errors.value)
    } else {
      const msg = responseErrors?.__all__ || err.response?.data?.detail || 'An error occurred while saving.'
      alertsStore.show({ type: 'error', title: 'Save Failed', message: msg })
    }
  } finally {
    saving.value = false
  }
}

async function handleDelete() {
  const success = await adminStore.deleteInstance(
    props.appLabel,
    props.modelName,
    props.id
  )

  if (success) {
    router.push(`/${props.appLabel}/${props.modelName}`)
  } else if (adminStore.error) {
    alertsStore.show({ type: 'error', title: 'Delete Failed', message: adminStore.error })
  }
  showDeleteConfirm.value = false
}

function handleCancel() {
  router.push(`/${props.appLabel}/${props.modelName}`)
}

function goToHistory() {
  router.push(`/${props.appLabel}/${props.modelName}/${props.id}/history`)
}

function handleAdd() {
  router.push(`/${props.appLabel}/${props.modelName}/add`)
}
</script>

<template>
  <div ref="formTopRef">
    <!-- Header -->
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
      <div>
        <nav class="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 mb-2">
          <RouterLink :to="`/${appLabel}/${modelName}`" class="hover:text-gray-700 dark:hover:text-gray-200">
            {{ model?.verbose_name_plural || modelName }}
          </RouterLink>
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
          </svg>
          <span class="text-gray-900 dark:text-white">{{ instance?.id || id }}</span>
        </nav>
        <h1 class="text-2xl font-bold text-gray-900 dark:text-white">
          Edit {{ model?.verbose_name || modelName }}
        </h1>
      </div>
      <div class="flex items-center flex-wrap gap-2">
        <button
          v-if="canAdd"
          class="btn btn-secondary text-sm flex items-center gap-1"
          title="Add new record"
          @click="handleAdd"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
          </svg>
          Add
        </button>
        <button
          v-if="isUserModel && canChange"
          class="btn btn-secondary text-sm"
          @click="showPasswordModal = true"
        >
          Change Password
        </button>
        <button
          class="btn btn-secondary text-sm"
          @click="goToHistory"
        >
          View History
        </button>
        <button
          v-if="canDelete"
          class="btn btn-danger text-sm"
          @click="showDeleteConfirm = true"
        >
          Delete
        </button>
      </div>
    </div>

    <!-- Loading state -->
    <div v-if="loading" class="flex items-center justify-center py-12">
      <svg class="animate-spin w-8 h-8 text-primary-600" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
      </svg>
    </div>

    <!-- Not found -->
    <div v-else-if="!instance" class="card p-8 text-center">
      <p class="text-gray-500 dark:text-gray-400">Item not found</p>
      <button class="btn btn-primary mt-4" @click="handleCancel">Go Back</button>
    </div>

    <!-- Form and Sidebar Grid -->
    <div v-else-if="model" class="grid grid-cols-1 lg:grid-cols-10 gap-10">
      <!-- Main Column: Form -->
      <div class="lg:col-span-7 space-y-6">
        <transition name="banner">
          <div v-if="errors.__all__" id="__all__" class="p-4 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-lg">
            <p class="text-sm text-red-600 dark:text-red-400">{{ errors.__all__ }}</p>
          </div>
        </transition>

        <!-- Success message -->
        <transition name="banner">
          <div v-if="showSuccess" class="p-4 bg-green-50 dark:bg-green-900/30 border border-green-200 dark:border-green-800 rounded-lg flex items-center gap-3">
            <svg class="w-5 h-5 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
            </svg>
            <p class="text-sm text-green-600 dark:text-green-400">Changes saved successfully!</p>
          </div>
        </transition>

        <form @submit.prevent="handleSubmit" novalidate>
          <div class="card p-6">
            <FormBuilder
              :model="model"
              v-model="formData"
              :errors="errors"
              :readonly-fields="model.readonly_fields"
              :disabled="!canChange"
              mode="edit"
            />
          </div>

          <!-- Child Tables -->
          <div v-if="model.child_tables && model.child_tables.length > 0" class="space-y-6">
            <ChildTable
              v-for="ct in model.child_tables"
              :key="ct.name"
              :config="ct"
              v-model="formData[ct.name]"
              :disabled="!canChange"
            />
          </div>

          <!-- Floating Actions Bar -->
          <div
            v-if="canChange"
            class="sticky bottom-0 z-20 mt-6 -mx-4 px-4 md:-mx-6 md:px-6 py-3 bg-white/90 dark:bg-gray-900/90 backdrop-blur border-t border-gray-200 dark:border-gray-700 flex items-center gap-4"
          >
            <button
              type="submit"
              :disabled="saving || !isDirty"
              class="btn btn-primary flex items-center gap-2"
              :class="{ 'opacity-50 cursor-not-allowed': !isDirty && !saving }"
            >
              <svg v-if="saving" class="animate-spin w-5 h-5" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
              </svg>
              {{ saving ? 'Saving...' : 'Save Changes' }}
            </button>
            <button
              type="button"
              class="btn btn-secondary"
              @click="handleCancel"
            >
              Cancel
            </button>
          </div>
        </form>
      </div>

      <!-- Sidebar Column: Metadata & History -->
      <div v-if="instance" class="lg:col-span-3">
        <InstanceSidebar
          ref="sidebarRef"
          :app-label="appLabel"
          :model-name="modelName"
          :instance="instance"
          :model="model"
          @go-to-history="goToHistory"
        />
      </div>
    </div>

    <!-- Delete confirmation modal -->
    <Teleport to="body">
      <div v-if="showDeleteConfirm" class="fixed inset-0 z-50 flex items-center justify-center">
        <div class="absolute inset-0 bg-black/50" @click="showDeleteConfirm = false"></div>
        <div class="relative bg-white dark:bg-gray-800 rounded-lg shadow-xl max-w-md w-full mx-4 p-6">
          <h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-4">Delete Confirmation</h3>
          <p class="text-gray-600 dark:text-gray-400 mb-6">
            Are you sure you want to delete this {{ model?.verbose_name || 'item' }}? This action cannot be undone.
          </p>
          <div class="flex justify-end gap-3">
            <button class="btn btn-secondary" @click="showDeleteConfirm = false">Cancel</button>
            <button class="btn btn-danger" @click="handleDelete">Delete</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Change User Password Modal -->
    <UserPasswordModal
      v-if="isUserModel"
      :show="showPasswordModal"
      :user-id="id"
      :username="instance?.username"
      @close="showPasswordModal = false"
      @success="showPasswordModal = false"
    />

    <LoadingOverlay :show="saving" />
  </div>
</template>
