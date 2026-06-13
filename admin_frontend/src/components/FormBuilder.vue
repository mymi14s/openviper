<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ModelConfig, ModelField } from '@/types/admin'
import ForeignKeyField from '@/components/ForeignKeyField.vue'
import FileUploadField from '@/components/FileUploadField.vue'
import CountrySelectField from '@/components/CountrySelectField.vue'
import PointFieldComponent from '@/components/PointField.vue'
import HtmlField from '@/components/HtmlField.vue'
import { formatFieldName, isValidUrl } from '@/utils/formatters'
import { getFieldType, getFieldComponent, getInputAttributes } from '@/utils/fieldHelpers'
import { formatDateTimeValue, parseDateTimeValue, formatValueForDisplay, parseValueFromDisplay } from '@/utils/dateTime'
import { getEditableFields } from '@/utils/formHelpers'

const props = defineProps<{
  model: ModelConfig
  modelValue: Record<string, unknown>
  errors?: Record<string, string>
  readonlyFields?: string[]
  disabled?: boolean
  mode?: 'create' | 'edit'
}>()

const validationErrors = ref<Record<string, string>>({})

const allErrors = computed(() => {
  return { ...props.errors, ...validationErrors.value }
})

const emit = defineEmits<{
  'update:modelValue': [value: Record<string, unknown>]
}>()

const formData = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

function updateField(fieldName: string, value: unknown) {
  emit('update:modelValue', { ...props.modelValue, [fieldName]: value })
}

function isReadonly(field: ModelField): boolean {
  // Always honor intrinsic readonly from field schema (e.g. AutoField, auto_now)
  if (field.readonly) return true

  // For policy-based readonlyFields (from ModelAdmin.readonly_fields):
  // Only apply them in 'edit' mode, allow editing in 'create' mode.
  if (props.mode === 'create') {
    return false
  }

  return props.readonlyFields?.includes(field.name) || false
}

const visibleFields = computed(() => {
  if (props.mode === 'create') {
    return props.model.fields.filter(f => !isReadonly(f))
  }
  return props.model.fields
})

const visibleFieldNames = computed(() => {
  return visibleFields.value.map(f => f.name)
})



function handleDateTimeChange(fieldName: string, value: string, fieldType: string) {
  const parsedValue = parseDateTimeValue(value, fieldType)
  updateField(fieldName, parsedValue)
}

const editableFields = computed(() => getEditableFields(props.model))

const editableFieldNames = computed(() => new Set(editableFields.value.map(f => f.name)))

const flatFields = computed(() => visibleFields.value.filter(f => editableFieldNames.value.has(f.name)))

const fieldsetFields = computed(() => {
  if (!props.model.fieldsets) return []
  return props.model.fieldsets.map((fieldset) => ({
    ...fieldset,
    visibleFields: fieldset.fields.filter((name: string) => visibleFieldNames.value.includes(name)),
  }))
})

const fieldsetFieldMap = computed(() => {
  const map: Record<string, ModelField> = {}
  for (const field of props.model.fields) {
    map[field.name] = field
  }
  return map
})

const fieldComponentMap = computed(() => {
  const map: Record<string, string> = {}
  for (const field of props.model.fields) {
    map[field.name] = getFieldComponent(field)
  }
  return map
})

const fieldTypeMap = computed(() => {
  const map: Record<string, string> = {}
  for (const field of props.model.fields) {
    map[field.name] = getFieldType(field)
  }
  return map
})

function getFieldLabel(field: ModelField): string {
  return field.label || formatFieldName(field.name)
}



function handleTextareaInput(fieldName: string, value: string, field: ModelField) {
  if (field.type === 'JSONField' && value) {
    try {
      JSON.parse(value)
      delete validationErrors.value[fieldName]
    } catch (e: unknown) {
      validationErrors.value[fieldName] = `Invalid JSON: ${e instanceof Error ? e.message : String(e)}`
    }
  } else {
    delete validationErrors.value[fieldName]
  }
  const parsed = parseValueFromDisplay(value, field)
  updateField(fieldName, parsed)
}
</script>

<template>
  <div class="space-y-6">
    <!-- Fieldsets or flat fields -->
    <template v-if="model.fieldsets && model.fieldsets.length > 0">
      <fieldset
        v-for="fieldset in fieldsetFields"
        :key="fieldset.name || 'default'"
        class="border border-gray-200 dark:border-gray-700 rounded-lg p-4"
      >
        <legend v-if="fieldset.name" class="px-2 text-sm font-medium text-gray-700 dark:text-gray-300">
          {{ fieldset.name }}
        </legend>
        <p v-if="fieldset.description" class="text-sm text-gray-500 dark:text-gray-400 mb-4">
          {{ fieldset.description }}
        </p>
        <div class="space-y-4">
          <div
            v-for="fieldName in fieldset.visibleFields"
            :key="fieldName"
            class="field-group"
            :class="{ 'has-error': allErrors?.[fieldName] }"
          >
            <template v-if="fieldsetFieldMap[fieldName]">
              <!-- Label -->
              <label
                :for="fieldName"
                class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
              >
                {{ getFieldLabel(fieldsetFieldMap[fieldName]) }}
                <span v-if="fieldsetFieldMap[fieldName].required" class="text-red-500">*</span>
              </label>

              <!-- Checkbox -->
              <div v-if="fieldComponentMap[fieldName] === 'checkbox'" class="flex items-center">
                <input
                  :id="fieldName"
                  type="checkbox"
                  :checked="!!formData[fieldName]"
                  :disabled="disabled || isReadonly(fieldsetFieldMap[fieldName])"
                  class="rounded border-gray-300 dark:border-gray-600 text-primary-600"
                  @change="updateField(fieldName, ($event.target as HTMLInputElement).checked)"
                />
                <span class="ml-2 text-sm text-gray-600 dark:text-gray-400">{{ fieldsetFieldMap[fieldName].help_text }}</span>
              </div>

              <!-- Select -->
              <select
                v-else-if="fieldComponentMap[fieldName] === 'select'"
                :id="fieldName"
                :value="formData[fieldName]"
                :disabled="disabled || isReadonly(fieldsetFieldMap[fieldName])"
                :required="fieldsetFieldMap[fieldName].required"
                class="w-full px-3 py-2"
                @change="updateField(fieldName, ($event.target as HTMLSelectElement).value)"
              >
                <option value="">Select...</option>
                <option
                  v-for="choice in fieldsetFieldMap[fieldName].choices"
                  :key="choice.value"
                  :value="choice.value"
                >
                  {{ choice.label }}
                </option>
              </select>

              <!-- ForeignKey -->
              <ForeignKeyField
                v-else-if="fieldComponentMap[fieldName] === 'foreignkey'"
                :model-value="formData[fieldName]"
                :related-model="fieldsetFieldMap[fieldName].related_model || ''"
                :disabled="disabled || isReadonly(fieldsetFieldMap[fieldName])"
                :required="fieldsetFieldMap[fieldName].required"
                :placeholder="fieldsetFieldMap[fieldName].help_text"
                @update:model-value="updateField(fieldName, $event)"
              />

              <!-- Country -->
              <CountrySelectField
                v-else-if="fieldComponentMap[fieldName] === 'country'"
                :model-value="formData[fieldName] ?? null"
                :choices="fieldsetFieldMap[fieldName].choices ?? []"
                :disabled="disabled || isReadonly(fieldsetFieldMap[fieldName])"
                :required="fieldsetFieldMap[fieldName].required"
                @update:model-value="updateField(fieldName, $event)"
              />

              <!-- File Upload -->
              <FileUploadField
                v-else-if="fieldComponentMap[fieldName] === 'file'"
                :field="fieldsetFieldMap[fieldName]"
                :model-value="formData[fieldName]"
                :disabled="disabled || isReadonly(fieldsetFieldMap[fieldName])"
                :required="fieldsetFieldMap[fieldName].required"
                @update:model-value="updateField(fieldName, $event)"
              />

              <!-- PointField -->
              <PointFieldComponent
                v-else-if="fieldComponentMap[fieldName] === 'point'"
                :model-value="formData[fieldName] ?? null"
                :srid="fieldsetFieldMap[fieldName].srid ?? 4326"
                :disabled="disabled || isReadonly(fieldsetFieldMap[fieldName])"
                :required="fieldsetFieldMap[fieldName].required"
                @update:model-value="updateField(fieldName, $event)"
              />

              <!-- HTMLField -->
              <HtmlField
                v-else-if="fieldComponentMap[fieldName] === 'html'"
                :model-value="formData[fieldName] ?? null"
                :disabled="disabled || isReadonly(fieldsetFieldMap[fieldName])"
                :required="fieldsetFieldMap[fieldName].required"
                :placeholder="fieldsetFieldMap[fieldName].help_text"
                @update:model-value="updateField(fieldName, $event)"
              />

              <!-- Textarea -->
              <textarea
                v-else-if="fieldComponentMap[fieldName] === 'textarea'"
                :id="fieldName"
                :value="formatValueForDisplay(formData[fieldName], fieldsetFieldMap[fieldName])"
                :disabled="disabled || isReadonly(fieldsetFieldMap[fieldName])"
                :required="fieldsetFieldMap[fieldName].required"
                :placeholder="fieldsetFieldMap[fieldName].help_text"
                rows="4"
                class="w-full px-3 py-2 font-mono text-sm"
                @input="handleTextareaInput(fieldName, ($event.target as HTMLTextAreaElement).value, fieldsetFieldMap[fieldName])"
              />

              <!-- URL Field -->
              <div v-else-if="fieldTypeMap[fieldName] === 'url'" class="space-y-1">
                <div v-if="isReadonly(fieldsetFieldMap[fieldName])" class="py-2">
                  <a
                    v-if="isValidUrl(formData[fieldName])"
                    :href="formData[fieldName]"
                    target="_blank" rel="noopener noreferrer"
                    class="text-primary-600 hover:text-primary-700 dark:text-primary-400 underline break-all"
                  >
                    {{ formData[fieldName] }}
                  </a>
                  <span v-else class="text-gray-500 dark:text-gray-400 italic">
                    {{ formData[fieldName] || 'Not set' }}
                  </span>
                </div>
                <div v-else class="flex space-x-2">
                  <input
                    :id="fieldName"
                    type="url"
                    :value="formData[fieldName]"
                    :disabled="disabled"
                    :required="fieldsetFieldMap[fieldName].required"
                    :placeholder="fieldsetFieldMap[fieldName].help_text"
                    v-bind="getInputAttributes(fieldsetFieldMap[fieldName])"
                    class="flex-1 px-3 py-2"
                    @input="updateField(fieldName, ($event.target as HTMLInputElement).value)"
                  />
                  <a
                    v-if="isValidUrl(formData[fieldName])"
                    :href="formData[fieldName]"
                    target="_blank" rel="noopener noreferrer"
                    class="inline-flex items-center px-3 py-2 border border-gray-300 dark:border-gray-600 shadow-sm text-sm font-medium rounded-md text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500"
                    title="Open link in new tab"
                  >
                    <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                    </svg>
                  </a>
                </div>
              </div>

              <!-- Input -->
              <input
                v-else
                :id="fieldName"
                :type="fieldTypeMap[fieldName]"
                :value="formatDateTimeValue(formData[fieldName], fieldTypeMap[fieldName])"
                :disabled="disabled || isReadonly(fieldsetFieldMap[fieldName])"
                :required="fieldsetFieldMap[fieldName].required"
                :placeholder="fieldsetFieldMap[fieldName].help_text"
                v-bind="getInputAttributes(fieldsetFieldMap[fieldName])"
                class="w-full px-3 py-2"
                @input="handleDateTimeChange(fieldName, ($event.target as HTMLInputElement).value, fieldTypeMap[fieldName])"
              />

              <!-- Help text -->
              <p v-if="fieldsetFieldMap[fieldName].help_text && fieldComponentMap[fieldName] !== 'checkbox' && fieldComponentMap[fieldName] !== 'file'" class="mt-1 text-xs text-gray-500 dark:text-gray-400">
                {{ fieldsetFieldMap[fieldName].help_text }}
              </p>

              <!-- Error -->
              <p v-if="allErrors?.[fieldName]" class="mt-1 text-xs text-red-600 dark:text-red-400">
                {{ allErrors[fieldName] }}
              </p>
            </template>
          </div>
        </div>
      </fieldset>
    </template>

    <!-- Flat fields (no fieldsets) -->
    <template v-else>
      <div
        v-for="field in flatFields"
        :key="field.name"
        class="field-group"
        :class="{ 'has-error': allErrors?.[field.name] }"
      >
        <!-- Label -->
        <label
          :for="field.name"
          class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
        >
          {{ getFieldLabel(field) }}
          <span v-if="field.required" class="text-red-500">*</span>
        </label>

        <!-- Checkbox -->
        <div v-if="fieldComponentMap[field.name] === 'checkbox'" class="flex items-center">
          <input
            :id="field.name"
            type="checkbox"
            :checked="formData[field.name]"
            :disabled="disabled || isReadonly(field)"
            class="rounded border-gray-300 dark:border-gray-600 text-primary-600"
            @change="updateField(field.name, ($event.target as HTMLInputElement).checked)"
          />
          <span v-if="field.help_text" class="ml-2 text-sm text-gray-600 dark:text-gray-400">
            {{ field.help_text }}
          </span>
        </div>

        <!-- Select -->
        <select
          v-else-if="fieldComponentMap[field.name] === 'select'"
          :id="field.name"
          :value="formData[field.name]"
          :disabled="disabled || isReadonly(field)"
          :required="field.required"
          class="w-full px-3 py-2"
          @change="updateField(field.name, ($event.target as HTMLSelectElement).value)"
        >
          <option value="">Select...</option>
          <option
            v-for="choice in field.choices"
            :key="choice.value"
            :value="choice.value"
          >
            {{ choice.label }}
          </option>
        </select>

        <!-- ForeignKey -->
        <ForeignKeyField
          v-else-if="fieldComponentMap[field.name] === 'foreignkey'"
          :model-value="formData[field.name]"
          :related-model="field.related_model || ''"
          :disabled="disabled || isReadonly(field)"
          :required="field.required"
          :placeholder="field.help_text"
          @update:model-value="updateField(field.name, $event)"
        />

        <!-- Country -->
        <CountrySelectField
          v-else-if="fieldComponentMap[field.name] === 'country'"
          :model-value="formData[field.name] ?? null"
          :choices="field.choices ?? []"
          :disabled="disabled || isReadonly(field)"
          :required="field.required"
          @update:model-value="updateField(field.name, $event)"
        />

        <!-- File Upload -->
        <FileUploadField
          v-else-if="fieldComponentMap[field.name] === 'file'"
          :field="field"
          :model-value="formData[field.name]"
          :disabled="disabled || isReadonly(field)"
          :required="field.required"
          @update:model-value="updateField(field.name, $event)"
        />

        <!-- PointField -->
        <PointFieldComponent
          v-else-if="fieldComponentMap[field.name] === 'point'"
          :model-value="formData[field.name] ?? null"
          :srid="field.srid ?? 4326"
          :disabled="disabled || isReadonly(field)"
          :required="field.required"
          @update:model-value="updateField(field.name, $event)"
        />

        <!-- HTMLField -->
        <HtmlField
          v-else-if="fieldComponentMap[field.name] === 'html'"
          :model-value="formData[field.name] ?? null"
          :disabled="disabled || isReadonly(field)"
          :required="field.required"
          :placeholder="field.help_text"
          @update:model-value="updateField(field.name, $event)"
        />

        <!-- Textarea -->
        <textarea
          v-else-if="fieldComponentMap[field.name] === 'textarea'"
          :id="field.name"
          :value="formatValueForDisplay(formData[field.name], field)"
          :disabled="disabled || isReadonly(field)"
          :required="field.required"
          :placeholder="field.help_text"
          rows="4"
          class="w-full px-3 py-2 font-mono text-sm"
          @input="handleTextareaInput(field.name, ($event.target as HTMLTextAreaElement).value, field)"
        />

        <!-- URL Field -->
        <div v-else-if="fieldTypeMap[field.name] === 'url'" class="space-y-1">
          <div v-if="isReadonly(field)" class="py-2">
            <a
              v-if="isValidUrl(formData[field.name])"
              :href="formData[field.name]"
              target="_blank" rel="noopener noreferrer"
              class="text-primary-600 hover:text-primary-700 dark:text-primary-400 underline break-all"
            >
              {{ formData[field.name] }}
            </a>
            <span v-else class="text-gray-500 dark:text-gray-400 italic">
              {{ formData[field.name] || 'Not set' }}
            </span>
          </div>
          <div v-else class="flex space-x-2">
            <input
              :id="field.name"
              type="url"
              :value="formData[field.name]"
              :disabled="disabled"
              :required="field.required"
              :placeholder="field.help_text"
              v-bind="getInputAttributes(field)"
              class="flex-1 px-3 py-2"
              @input="updateField(field.name, ($event.target as HTMLInputElement).value)"
            />
            <a
              v-if="isValidUrl(formData[field.name])"
              :href="formData[field.name]"
              target="_blank" rel="noopener noreferrer"
              class="inline-flex items-center px-3 py-2 border border-gray-300 dark:border-gray-600 shadow-sm text-sm font-medium rounded-md text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500"
              title="Open link in new tab"
            >
              <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
              </svg>
            </a>
          </div>
        </div>

        <!-- Input -->
        <input
          v-else
          :id="field.name"
          :type="fieldTypeMap[field.name]"
          :value="formatDateTimeValue(formData[field.name], fieldTypeMap[field.name])"
          :disabled="disabled || isReadonly(field)"
          :required="field.required"
          :placeholder="field.help_text"
          v-bind="getInputAttributes(field)"
          class="w-full px-3 py-2"
          @input="handleDateTimeChange(field.name, ($event.target as HTMLInputElement).value, fieldTypeMap[field.name])"
        />

        <!-- Help text -->
        <p v-if="field.help_text && fieldComponentMap[field.name] !== 'checkbox' && fieldComponentMap[field.name] !== 'file'" class="mt-1 text-xs text-gray-500 dark:text-gray-400">
          {{ field.help_text }}
        </p>

        <!-- Error -->
        <p v-if="allErrors?.[field.name]" class="mt-1 text-xs text-red-600 dark:text-red-400">
          {{ allErrors[field.name] }}
        </p>
      </div>
    </template>
  </div>
</template>
