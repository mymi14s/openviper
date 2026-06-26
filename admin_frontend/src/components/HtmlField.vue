<script setup lang="ts">
import { ref, computed, watch } from 'vue'

const props = defineProps<{
  modelValue: string | null | undefined
  disabled?: boolean
  required?: boolean
  placeholder?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string | null): void
}>()

const rawValue = ref(typeof props.modelValue === 'string' ? props.modelValue : '')
const showPreview = ref(false)
const isFocused = ref(false)

const SAFE_ATTRS = /^(href|title|alt|src|colspan|rowspan|scope|class|id|name|type|value|disabled|checked|target|rel|start|reversed|label|datetime|cite|abbr|headers|scope|span|width|align|valign)$/i
const DANGEROUS_TAGS = /^(script|style|iframe|object|embed|applet|form|input|button|select|textarea|link|meta|base|svg|math)$/i

function sanitize(html: string): string {
  const el = document.createElement('div')
  el.innerHTML = html
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_ELEMENT)
  const toRemove: Element[] = []
  while (walker.nextNode()) {
    const node = walker.currentNode as Element
    if (DANGEROUS_TAGS.test(node.tagName)) {
      toRemove.push(node)
    } else {
      for (let i = node.attributes.length - 1; i >= 0; i--) {
        const attr = node.attributes[i]
        if (!SAFE_ATTRS.test(attr.name)) {
          node.removeAttribute(attr.name)
        }
        if (attr.name === 'href' && attr.value && attr.value.trim().toLowerCase().startsWith('javascript:')) {
          node.removeAttribute(attr.name)
        }
      }
    }
  }
  for (const node of toRemove) {
    node.parentNode?.removeChild(node)
  }
  return el.innerHTML
}

const sanitizedPreview = computed(() => {
  const val = rawValue.value
  if (!val) return ''
  return sanitize(val)
})

function handleInput(event: Event) {
  const value = (event.target as HTMLTextAreaElement).value
  rawValue.value = value
  emit('update:modelValue', value || null)
}

watch(() => props.modelValue, (newVal) => {
  if (typeof newVal === 'string') {
    rawValue.value = newVal
  } else {
    rawValue.value = ''
  }
})
</script>

<template>
  <div class="html-field-wrapper">
    <div class="flex items-center justify-between mb-1">
      <div class="flex items-center gap-2">
        <button
          type="button"
          :class="[
            'px-2.5 py-1 text-xs font-medium rounded-l-md border',
            !showPreview
              ? 'bg-primary-600 text-white border-primary-600'
              : 'bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-600'
          ]"
          @click="showPreview = false"
        >
          Edit
        </button>
        <button
          type="button"
          :class="[
            'px-2.5 py-1 text-xs font-medium rounded-r-md border',
            showPreview
              ? 'bg-primary-600 text-white border-primary-600'
              : 'bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-600'
          ]"
          @click="showPreview = true"
        >
          Preview
        </button>
      </div>
      <span v-if="rawValue.length > 0" class="text-xs text-gray-400 dark:text-gray-500">
        {{ rawValue.length }} chars
      </span>
    </div>

    <!-- Edit mode -->
    <textarea
      v-if="!showPreview"
      :value="rawValue"
      :disabled="disabled"
      :required="required"
      :placeholder="placeholder"
      rows="6"
      class="w-full px-3 py-2 font-mono text-sm border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
      :class="{ 'ring-2 ring-red-400 dark:ring-red-500': isFocused && !rawValue && required }"
      @input="handleInput"
      @focus="isFocused = true"
      @blur="isFocused = false"
    />

    <!-- Preview mode -->
    <div
      v-else
      class="w-full min-h-[150px] px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 prose prose-sm dark:prose-invert max-w-none overflow-auto"
      :class="{ 'opacity-50 cursor-not-allowed': disabled }"
      v-html="sanitizedPreview"
    />

    <p v-if="!disabled && !showPreview" class="mt-1 text-xs text-gray-400 dark:text-gray-500">
      HTML content is sanitized on save. Allowed tags: p, br, strong, em, a, ul, ol, li, blockquote, code, pre, img, sub, sup, abbr, h1-h6.
    </p>
  </div>
</template>
