<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import type { ModelField } from '@/types/admin'

const props = defineProps<{
  field: ModelField
  modelValue: string | File | null
  disabled?: boolean
  required?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: File | null | string]
}>()

const fileInput = ref<HTMLInputElement | null>(null)
const previewUrl = ref<string | null>(null)
const dragOver = ref(false)

const isImageField = computed(() => {
  return props.field.type === 'ImageField' || props.field.component === 'image'
})

const acceptTypes = computed(() => {
  return isImageField.value ? 'image/*' : undefined
})

const currentFile = computed(() => {
  if (props.modelValue instanceof File) {
    return {
      name: props.modelValue.name,
      size: formatFileSize(props.modelValue.size),
      isNew: true
    }
  }
  return null
})

const existingFilePath = computed(() => {
  if (typeof props.modelValue === 'string' && props.modelValue) {
    return props.modelValue
  }
  return null
})

const existingFileUrl = computed(() => {
  if (existingFilePath.value) {
    // Construct URL from path - assumes MEDIA_URL is /media/
    const path = existingFilePath.value.startsWith('/')
      ? existingFilePath.value
      : `/media/${existingFilePath.value}`
    return path
  }
  return null
})

const displayPreview = computed(() => {
  // For new files, show the created object URL
  if (previewUrl.value) {
    return previewUrl.value
  }
  // For existing images, show the URL
  if (isImageField.value && existingFileUrl.value) {
    return existingFileUrl.value
  }
  return null
})

function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

function handleFileChange(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0] || null

  if (file) {
    emit('update:modelValue', file)

    // Create preview for images
    if (isImageField.value && file.type.startsWith('image/')) {
      previewUrl.value = URL.createObjectURL(file)
    }
  }
}

function handleDrop(event: DragEvent) {
  event.preventDefault()
  dragOver.value = false

  if (props.disabled) return

  const file = event.dataTransfer?.files?.[0]
  if (file) {
    // Check if file type matches accept filter
    if (isImageField.value && !file.type.startsWith('image/')) {
      return
    }

    emit('update:modelValue', file)

    if (isImageField.value && file.type.startsWith('image/')) {
      previewUrl.value = URL.createObjectURL(file)
    }
  }
}

function handleDragOver(event: DragEvent) {
  event.preventDefault()
  if (!props.disabled) {
    dragOver.value = true
  }
}

function handleDragLeave() {
  dragOver.value = false
}

function clearFile() {
  emit('update:modelValue', null)
  previewUrl.value = null
  if (fileInput.value) {
    fileInput.value.value = ''
  }
}

function openFilePicker() {
  if (!props.disabled) {
    fileInput.value?.click()
  }
}

// Clean up object URLs on unmount
watch(previewUrl, (newUrl, oldUrl) => {
  if (oldUrl && oldUrl.startsWith('blob:')) {
    URL.revokeObjectURL(oldUrl)
  }
})
</script>

<template>
  <div class="file-upload-field">
    <!-- Hidden file input -->
    <input
      ref="fileInput"
      type="file"
      :accept="acceptTypes"
      :disabled="disabled"
      class="hidden"
      @change="handleFileChange"
    />

    <!-- Drop zone / Upload area -->
    <div
      :class="[
        'border-2 border-dashed rounded-lg transition-colors cursor-pointer',
        dragOver ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/20' : 'border-gray-300 dark:border-gray-600',
        disabled ? 'opacity-50 cursor-not-allowed' : 'hover:border-primary-400'
      ]"
      @click="openFilePicker"
      @drop="handleDrop"
      @dragover="handleDragOver"
      @dragleave="handleDragLeave"
    >
      <!-- Image preview -->
      <template v-if="isImageField && displayPreview">
        <div class="relative p-2">
          <img
            :src="displayPreview"
            :alt="field.name"
            class="max-h-48 max-w-full mx-auto rounded object-contain"
          />
          <button
            v-if="!disabled"
            type="button"
            class="absolute top-3 right-3 p-1.5 bg-red-500 text-white rounded-full hover:bg-red-600 transition-colors shadow-md"
            title="Remove file"
            @click.stop="clearFile"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
          <div v-if="currentFile" class="text-center text-sm text-gray-500 dark:text-gray-400 mt-2">
            {{ currentFile.name }} ({{ currentFile.size }})
          </div>
          <div v-else-if="existingFilePath" class="text-center text-xs text-gray-500 dark:text-gray-400 mt-2">
            <span class="font-mono">{{ existingFilePath.split('/').pop() }}</span>
          </div>
        </div>
      </template>

      <!-- File (non-image) display -->
      <template v-else-if="currentFile || existingFilePath">
        <div class="p-4 flex items-center justify-between">
          <div class="flex items-center space-x-3">
            <svg class="w-8 h-8 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
            </svg>
            <div>
              <template v-if="currentFile">
                <p class="text-sm font-medium text-gray-700 dark:text-gray-300">{{ currentFile.name }}</p>
                <p class="text-xs text-gray-500 dark:text-gray-400">{{ currentFile.size }}</p>
              </template>
              <template v-else-if="existingFilePath">
                <p class="text-sm font-medium text-gray-700 dark:text-gray-300 font-mono">{{ existingFilePath.split('/').pop() }}</p>
                <a
                  :href="existingFileUrl"
                  target="_blank"
                  class="text-xs text-primary-600 hover:text-primary-700 dark:text-primary-400"
                  @click.stop
                >
                  View file
                </a>
              </template>
            </div>
          </div>
          <button
            v-if="!disabled"
            type="button"
            class="p-2 text-red-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded transition-colors"
            title="Remove file"
            @click.stop="clearFile"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
          </button>
        </div>
      </template>

      <!-- Empty state / Upload prompt -->
      <template v-else>
        <div class="p-6 text-center">
          <svg class="w-10 h-10 mx-auto text-gray-400 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              v-if="isImageField"
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"
            />
            <path
              v-else
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
            />
          </svg>
          <p class="text-sm text-gray-600 dark:text-gray-400">
            <span class="font-medium text-primary-600 dark:text-primary-400">Click to upload</span>
            or drag and drop
          </p>
          <p v-if="isImageField" class="text-xs text-gray-500 dark:text-gray-500 mt-1">
            PNG, JPG, GIF, WebP, SVG
          </p>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.file-upload-field {
  width: 100%;
}

.hidden {
  display: none;
}
</style>
