<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { modelsApi } from '@/api/client'
import type { ModelConfig } from '@/types/admin'
import FormBuilder from '@/components/FormBuilder.vue'

const props = defineProps<{
  /** "appLabel/modelName" e.g. "auth/user" */
  relatedModel: string
  mode: 'create' | 'view'
  /** Required only when mode === 'view' */
  recordId?: number | string | null
}>()

const emit = defineEmits<{
  close: []
  /** Emitted after a successful create with the raw API response */
  created: [record: Record<string, any>]
}>()

const isLoading = ref(false)
const isSaving  = ref(false)
const modelConfig = ref<ModelConfig | null>(null)
const formData    = ref<Record<string, any>>({})
const errors      = ref<Record<string, string>>({})
const saveError   = ref<string | null>(null)

// --------------------------------------------------------------------------
// Parsed model coordinates
// --------------------------------------------------------------------------

const parsedModel = computed(() => {
  if (!props.relatedModel) return { appLabel: '', modelName: '' }
  const parts = props.relatedModel.split('/')
  return parts.length === 2
    ? { appLabel: parts[0], modelName: parts[1] }
    : { appLabel: 'default', modelName: props.relatedModel }
})

// --------------------------------------------------------------------------
// Responsive modal width based on field count
// --------------------------------------------------------------------------

const modalWidthClass = computed(() => {
  const fields = modelConfig.value?.fields?.filter(
    f => !['id', 'created_at', 'updated_at'].includes(f.name)
  ) ?? []
  if (fields.length <= 4) return 'max-w-lg'
  if (fields.length <= 8) return 'max-w-2xl'
  return 'max-w-4xl'
})

const title = computed(() => {
  const name = modelConfig.value?.verbose_name ?? parsedModel.value.modelName
  return props.mode === 'view' ? `View ${name}` : `Add ${name}`
})

// --------------------------------------------------------------------------
// Data loading
// --------------------------------------------------------------------------

async function loadModel() {
  const { appLabel, modelName } = parsedModel.value
  if (!appLabel || !modelName) return

  isLoading.value = true
  try {
    const config = await modelsApi.getModel(appLabel, modelName)
    modelConfig.value = config

    if (props.mode === 'create') {
      // Initialise form with field defaults
      const defaults: Record<string, any> = {}
      for (const field of config.fields) {
        if (['id', 'created_at', 'updated_at'].includes(field.name)) continue
        defaults[field.name] = field.default ?? null
      }
      formData.value = defaults
    } else if (props.mode === 'view' && props.recordId != null) {
      // Fetch the existing record
      const instance = await modelsApi.getModelInstance(
        appLabel, modelName, String(props.recordId)
      )
      formData.value = { ...(instance as Record<string, any>) }
    }
  } catch (e) {
    console.error('[ForeignKeyModal] failed to load model:', e)
  } finally {
    isLoading.value = false
  }
}

// --------------------------------------------------------------------------
// Save
// --------------------------------------------------------------------------

async function handleSave() {
  if (props.mode !== 'create') return
  const { appLabel, modelName } = parsedModel.value

  isSaving.value  = true
  errors.value    = {}
  saveError.value = null

  try {
    const record = await modelsApi.createModelInstance(appLabel, modelName, formData.value)
    emit('created', record as Record<string, any>)
    emit('close')
  } catch (err: any) {
    if (err.response?.data?.errors) {
      errors.value = err.response.data.errors
    } else {
      saveError.value = err.response?.data?.detail ?? 'An error occurred while saving.'
    }
  } finally {
    isSaving.value = false
  }
}

// --------------------------------------------------------------------------
// Keyboard: Escape → close
// --------------------------------------------------------------------------

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}

onMounted(() => {
  loadModel()
  window.addEventListener('keydown', onKeydown)
})

import { onUnmounted } from 'vue'
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <div
      class="fixed inset-0 z-[99999] flex items-start justify-center bg-black/50 p-4 pt-16 overflow-y-auto"
      @click.self="emit('close')"
    >
      <div
        class="relative w-full bg-white dark:bg-gray-800 rounded-lg shadow-xl flex flex-col my-4"
        :class="modalWidthClass"
      >
        <!-- ── Header ──────────────────────────────────────────────────── -->
        <div class="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h2 class="text-lg font-semibold text-gray-900 dark:text-gray-100">
            {{ title }}
          </h2>
          <button
            type="button"
            title="Close"
            class="ml-4 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 rounded p-1 transition-colors"
            @click="emit('close')"
          >
            <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- ── Body ───────────────────────────────────────────────────── -->
        <div class="px-6 py-5 overflow-y-auto">
          <!-- Loading spinner -->
          <div v-if="isLoading" class="flex items-center justify-center py-16">
            <svg class="animate-spin h-8 w-8 text-primary-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/>
            </svg>
          </div>

          <!-- The actual form -->
          <form
            v-else-if="modelConfig"
            id="fk-modal-form"
            class="space-y-4"
            @submit.prevent="handleSave"
          >
            <FormBuilder
              :model="modelConfig"
              v-model="formData"
              :errors="errors"
              :disabled="mode === 'view'"
              :mode="mode"
            />
          </form>

          <!-- Top-level error message -->
          <p
            v-if="saveError"
            class="mt-3 text-sm text-red-600 dark:text-red-400"
          >
            {{ saveError }}
          </p>
        </div>

        <!-- ── Footer ─────────────────────────────────────────────────── -->
        <div class="flex justify-end gap-3 px-6 py-4 border-t border-gray-200 dark:border-gray-700">
          <button
            type="button"
            class="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300
                   bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600
                   rounded-md hover:bg-gray-50 dark:hover:bg-gray-600 transition-colors"
            @click="emit('close')"
          >
            {{ mode === 'view' ? 'Close' : 'Cancel' }}
          </button>

          <button
            v-if="mode === 'create'"
            type="submit"
            form="fk-modal-form"
            :disabled="isSaving || isLoading"
            class="px-4 py-2 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700
                   disabled:opacity-50 disabled:cursor-not-allowed rounded-md transition-colors"
          >
            <span v-if="isSaving" class="flex items-center gap-2">
              <svg class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/>
              </svg>
              Saving…
            </span>
            <span v-else>Save</span>
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
