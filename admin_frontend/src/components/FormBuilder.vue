<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ModelConfig, ModelField } from '@/types/admin'
import ForeignKeyField from '@/components/ForeignKeyField.vue'
import FileUploadField from '@/components/FileUploadField.vue'
import { formatFieldName } from '@/utils/formatters'

const props = defineProps<{
  model: ModelConfig
  modelValue: Record<string, any>
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
  'update:modelValue': [value: Record<string, any>]
}>()

const formData = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

function updateField(fieldName: string, value: any) {
  emit('update:modelValue', { ...props.modelValue, [fieldName]: value })
}

function isReadonly(field: ModelField): boolean {
  return field.readonly || props.readonlyFields?.includes(field.name) || false
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

function getFieldType(field: ModelField): string {
  // Map model field types to input types
  const typeMap: Record<string, string> = {
    // Generic types (lowercase variants)
    text: 'text',
    string: 'text',
    email: 'email',
    url: 'url',
    number: 'number',
    password: 'password',
    date: 'date',
    datetime: 'datetime-local',
    time: 'time',
    boolean: 'checkbox',
    textarea: 'textarea',
    select: 'select',
    file: 'file',
    image: 'file',

    // CharField variants
    CharField: 'text',
    SlugField: 'text',
    IPAddressField: 'text',

    // Email
    EmailField: 'email',

    // URL
    URLField: 'url',

    // Number types
    IntegerField: 'number',
    BigIntegerField: 'number',
    PositiveIntegerField: 'number',
    AutoField: 'number',
    FloatField: 'number',
    DecimalField: 'number',

    // Password
    PasswordField: 'password',

    // Date/Time
    DateField: 'date',
    DateTimeField: 'datetime-local',
    TimeField: 'time',

    // Boolean
    BooleanField: 'checkbox',

    // Text areas
    TextField: 'textarea',
    JSONField: 'textarea',

    // UUID
    UUIDField: 'text',

    // Foreign keys and relationships
    ForeignKey: 'select',
    OneToOneField: 'select',
    ManyToManyField: 'select',

    // File uploads
    FileField: 'file',
    ImageField: 'file',
  }
  return typeMap[field.type] || 'text'
}

function getFieldComponent(field: ModelField): string {
  // Check for file upload fields first
  if (field.type === 'FileField' || field.type === 'ImageField' ||
      field.component === 'file' || field.component === 'image') {
    return 'file'
  }
  // Check for foreignkey field (has related_model)
  if (field.related_model) return 'foreignkey'
  const inputType = getFieldType(field)
  if (field.choices && field.choices.length > 0) return 'select'
  if (inputType === 'checkbox') return 'checkbox'
  if (inputType === 'textarea') return 'textarea'
  if (inputType === 'select') return 'select'
  return 'input'
}

function getInputAttributes(field: ModelField): Record<string, any> {
  const attrs: Record<string, any> = {}
  const fieldType = getFieldType(field)

  // Add max length for text fields
  if (field.max_length) {
    attrs.maxlength = field.max_length
  }

  // Add min/max/step for number fields
  if (fieldType === 'number') {
    if (field.min_value !== undefined && field.min_value !== null) {
      attrs.min = field.min_value
    }
    if (field.max_value !== undefined && field.max_value !== null) {
      attrs.max = field.max_value
    }
    // Add step for float/decimal fields
    if (field.type === 'FloatField' || field.type === 'DecimalField') {
      attrs.step = '0.01'
    } else {
      attrs.step = '1'
    }
  }

  // Add pattern for specific field types
  if (field.type === 'IPAddressField') {
    attrs.pattern = '^(\\d{1,3}\\.){3}\\d{1,3}$'
    attrs.placeholder = 'e.g., 192.168.1.1'
  } else if (field.type === 'SlugField') {
    attrs.pattern = '^[a-z0-9]+(?:-[a-z0-9]+)*$'
    attrs.placeholder = 'lowercase-with-hyphens'
  } else if (field.type === 'UUIDField') {
    attrs.pattern = '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    attrs.readonly = true // Usually auto-generated
  }

  return attrs
}

function formatDateTimeValue(value: any, fieldType: string): string {
  if (!value) return ''
  
  // Handle datetime-local fields
  if (fieldType === 'datetime-local' || fieldType === 'DateTimeField') {
    // Convert ISO 8601 format (2024-02-22T10:30:00) to datetime-local format
    const date = new Date(value)
    if (isNaN(date.getTime())) return ''
    
    // Format as YYYY-MM-DDTHH:mm for datetime-local input
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    const hours = String(date.getHours()).padStart(2, '0')
    const minutes = String(date.getMinutes()).padStart(2, '0')
    
    return `${year}-${month}-${day}T${hours}:${minutes}`
  }
  
  // Handle date fields
  if (fieldType === 'date' || fieldType === 'DateField') {
    const date = new Date(value)
    if (isNaN(date.getTime())) return ''
    
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    
    return `${year}-${month}-${day}`
  }
  
  // Handle time fields
  if (fieldType === 'time' || fieldType === 'TimeField') {
    const date = new Date(value)
    if (isNaN(date.getTime())) return ''
    
    const hours = String(date.getHours()).padStart(2, '0')
    const minutes = String(date.getMinutes()).padStart(2, '0')
    
    return `${hours}:${minutes}`
  }
  
  return String(value)
}

function parseDateTimeValue(value: string, fieldType: string): any {
  if (!value) return null
  
  // For datetime-local, date, and time inputs, convert back to ISO format
  if (fieldType === 'datetime-local' || fieldType === 'DateTimeField') {
    // Convert from YYYY-MM-DDTHH:mm to ISO 8601
    const date = new Date(value)
    if (isNaN(date.getTime())) return value // Return original if invalid
    return date.toISOString()
  }
  
  if (fieldType === 'date' || fieldType === 'DateField') {
    // Value is already in ISO format (YYYY-MM-DD)
    return value
  }
  
  if (fieldType === 'time' || fieldType === 'TimeField') {
    // Return time as is
    return value
  }
  
  return value
}

function handleDateTimeChange(fieldName: string, value: string, fieldType: string) {
  const parsedValue = parseDateTimeValue(value, fieldType)
  updateField(fieldName, parsedValue)
}

function getEditableFields(): ModelField[] {
  // Filter out auto-generated fields that shouldn't be edited
  return props.model.fields.filter((field) => {
    if (field.name === 'id') return false
    if (field.name === 'created_at' || field.name === 'updated_at') return false
    return true
  })
}

function getFieldLabel(field: ModelField): string {
  return field.label || formatFieldName(field.name)
}

function formatValueForDisplay(value: any, field: ModelField): string {
  if (value === null || value === undefined) return ''

  // For JSON fields, pretty-print objects
  if (field.type === 'JSONField') {
    if (typeof value === 'object') {
      return JSON.stringify(value, null, 2)
    }
    return String(value)
  }

  // For regular textareas with objects (shouldn't happen but handle it)
  if (typeof value === 'object') {
    return JSON.stringify(value, null, 2)
  }

  return String(value)
}

function parseValueFromDisplay(value: string, field: ModelField): any {
  if (!value) return field.type === 'JSONField' ? null : value

  // For JSON fields, parse the JSON string
  if (field.type === 'JSONField') {
    try {
      return JSON.parse(value)
    } catch {
      // If it's not valid JSON, return as-is (validation will catch it)
      return value
    }
  }

  return value
}

function handleTextareaInput(fieldName: string, value: string, field: ModelField) {
  if (field.type === 'JSONField' && value) {
    try {
      JSON.parse(value)
      delete validationErrors.value[fieldName]
    } catch (e: any) {
      validationErrors.value[fieldName] = `Invalid JSON: ${e.message}`
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
        v-for="fieldset in model.fieldsets"
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
            v-for="fieldName in fieldset.fields.filter(name => visibleFieldNames.includes(name))"
            :key="fieldName"
            class="field-group"
            :class="{ 'has-error': allErrors?.[fieldName] }"
          >
            <template v-for="field in model.fields.filter(f => f.name === fieldName)" :key="field.name">
              <!-- Label -->
              <label
                :for="field.name"
                class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
              >
                {{ getFieldLabel(field) }}
                <span v-if="field.required" class="text-red-500">*</span>
              </label>

              <!-- Checkbox -->
              <div v-if="getFieldComponent(field) === 'checkbox'" class="flex items-center">
                <input
                  :id="field.name"
                  type="checkbox"
                  :checked="!!formData[field.name]"
                  :disabled="disabled || isReadonly(field)"
                  class="rounded border-gray-300 dark:border-gray-600 text-primary-600"
                  @change="updateField(field.name, ($event.target as HTMLInputElement).checked)"
                />
                <span class="ml-2 text-sm text-gray-600 dark:text-gray-400">{{ field.help_text }}</span>
              </div>

              <!-- Select -->
              <select
                v-else-if="getFieldComponent(field) === 'select'"
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
                v-else-if="getFieldComponent(field) === 'foreignkey'"
                :model-value="formData[field.name]"
                :related-model="field.related_model || ''"
                :disabled="disabled || isReadonly(field)"
                :required="field.required"
                :placeholder="field.help_text"
                @update:model-value="updateField(field.name, $event)"
              />

              <!-- File Upload -->
              <FileUploadField
                v-else-if="getFieldComponent(field) === 'file'"
                :field="field"
                :model-value="formData[field.name]"
                :disabled="disabled || isReadonly(field)"
                :required="field.required"
                @update:model-value="updateField(field.name, $event)"
              />

              <!-- Textarea -->
              <textarea
                v-else-if="getFieldComponent(field) === 'textarea'"
                :id="field.name"
                :value="formatValueForDisplay(formData[field.name], field)"
                :disabled="disabled || isReadonly(field)"
                :required="field.required"
                :placeholder="field.help_text"
                rows="4"
                class="w-full px-3 py-2 font-mono text-sm"
                @input="handleTextareaInput(field.name, ($event.target as HTMLTextAreaElement).value, field)"
              />

              <!-- Input -->
              <input
                v-else
                :id="field.name"
                :type="getFieldType(field)"
                :value="formatDateTimeValue(formData[field.name], getFieldType(field))"
                :disabled="disabled || isReadonly(field)"
                :required="field.required"
                :placeholder="field.help_text"
                v-bind="getInputAttributes(field)"
                class="w-full px-3 py-2"
                @input="handleDateTimeChange(field.name, ($event.target as HTMLInputElement).value, getFieldType(field))"
              />

              <!-- Help text -->
              <p v-if="field.help_text && getFieldComponent(field) !== 'checkbox' && getFieldComponent(field) !== 'file'" class="mt-1 text-xs text-gray-500 dark:text-gray-400">
                {{ field.help_text }}
              </p>

              <!-- Error -->
              <p v-if="allErrors?.[field.name]" class="mt-1 text-xs text-red-600 dark:text-red-400">
                {{ allErrors[field.name] }}
              </p>
            </template>
          </div>
        </div>
      </fieldset>
    </template>

    <!-- Flat fields (no fieldsets) -->
    <template v-else>
      <div
        v-for="field in visibleFields.filter(f => getEditableFields().some(ef => ef.name === f.name))"
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
        <div v-if="getFieldComponent(field) === 'checkbox'" class="flex items-center">
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
          v-else-if="getFieldComponent(field) === 'select'"
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
          v-else-if="getFieldComponent(field) === 'foreignkey'"
          :model-value="formData[field.name]"
          :related-model="field.related_model || ''"
          :disabled="disabled || isReadonly(field)"
          :required="field.required"
          :placeholder="field.help_text"
          @update:model-value="updateField(field.name, $event)"
        />

        <!-- File Upload -->
        <FileUploadField
          v-else-if="getFieldComponent(field) === 'file'"
          :field="field"
          :model-value="formData[field.name]"
          :disabled="disabled || isReadonly(field)"
          :required="field.required"
          @update:model-value="updateField(field.name, $event)"
        />

        <!-- Textarea -->
        <textarea
          v-else-if="getFieldComponent(field) === 'textarea'"
          :id="field.name"
          :value="formatValueForDisplay(formData[field.name], field)"
          :disabled="disabled || isReadonly(field)"
          :required="field.required"
          :placeholder="field.help_text"
          rows="4"
          class="w-full px-3 py-2 font-mono text-sm"
          @input="handleTextareaInput(field.name, ($event.target as HTMLTextAreaElement).value, field)"
        />

        <!-- Input -->
        <input
          v-else
          :id="field.name"
          :type="getFieldType(field)"
          :value="formatDateTimeValue(formData[field.name], getFieldType(field))"
          :disabled="disabled || isReadonly(field)"
          :required="field.required"
          :placeholder="field.help_text"
          v-bind="getInputAttributes(field)"
          class="w-full px-3 py-2"
          @input="handleDateTimeChange(field.name, ($event.target as HTMLInputElement).value, getFieldType(field))"
        />

        <!-- Help text -->
        <p v-if="field.help_text && getFieldComponent(field) !== 'checkbox' && getFieldComponent(field) !== 'file'" class="mt-1 text-xs text-gray-500 dark:text-gray-400">
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
