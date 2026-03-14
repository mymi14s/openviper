// Admin types
export interface User {
  id: number
  username: string
  email: string
  is_superuser: boolean
  is_staff: boolean
  is_active: boolean
  date_joined?: string
  last_login?: string
}

export interface ModelField {
  name: string
  type: string
  label: string
  required: boolean
  readonly: boolean
  help_text?: string
  choices?: Array<{ value: string | number; label: string }>
  default?: any
  max_length?: number
  min_value?: number
  max_value?: number
  related_model?: string
  component?: string
}

export interface ChildTableConfig {
  name: string
  label: string
  model: string
  fk_name: string | null
  fields: Record<string, ModelField>
  display_fields: string[]
}

export interface ModelConfig {
  name: string
  app: string
  table: string
  verbose_name: string
  verbose_name_plural: string
  list_display: string[]
  list_filter: string[]
  search_fields: string[]
  ordering: string[]
  list_per_page: number
  fields: ModelField[]
  fieldsets?: Array<{
    name: string | null
    fields: string[]
    classes?: string[]
    description?: string
  }>
  readonly_fields: string[]
  actions: string[]
  permissions?: {
    add: boolean
    change: boolean
    delete: boolean
    view: boolean
  }
  child_tables?: ChildTableConfig[]
  list_display_styles?: Record<string, string>
}

export interface ModelInstance {
  id: number | string
  [key: string]: any
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  per_page: number
  total_pages: number
  permission_denied?: boolean
  permission_message?: string
}

export interface ChangeHistoryEntry {
  id: number
  model_name: string
  object_id: string
  object_repr?: string
  action: 'create' | 'update' | 'delete'
  changed_by?: string
  change_time?: string
  message?: string
  changed_fields?: Record<string, { old: any; new: any }>
}

export interface AdminAction {
  name: string
  label: string
  description?: string
  requires_confirmation: boolean
}

export interface DashboardStats {
  stats: Record<string, number>
  recent_activity: ChangeHistoryEntry[]
  models_count: number
}

// API response types
export interface ApiResponse<T = any> {
  data?: T
  error?: string
  message?: string
}

export interface AdminConfig {
  admin_title: string
  admin_header_title: string
  admin_footer_title: string
  user_model?: string
  auth_user_model?: string
  is_custom_user?: boolean
}


export interface LoginRequest {
  username: string
  password: string
}

export interface LoginResponse {
  access_token: string
  refresh_token: string
  user: User
}

// Form types
export interface FormState {
  values: Record<string, any>
  errors: Record<string, string>
  isDirty: boolean
  isSubmitting: boolean
}

// Plugin types
export interface AdminPlugin {
  name: string
  version: string
  install: (app: any, options?: any) => void
  components?: Record<string, any>
  routes?: any[]
  hooks?: {
    onModelLoad?: (config: ModelConfig) => void
    onBeforeSave?: (model: string, data: any) => any
    onAfterSave?: (model: string, data: any) => void
    onBeforeDelete?: (model: string, id: string | number) => boolean
  }
}

// Theme types
export type ThemeMode = 'light' | 'dark' | 'system'

// Filter types
export interface FilterValue {
  field: string
  operator: 'eq' | 'ne' | 'gt' | 'gte' | 'lt' | 'lte' | 'contains' | 'startswith' | 'endswith' | 'in' | 'isnull'
  value: any
}

// Sort types
export interface SortValue {
  field: string
  direction: 'asc' | 'desc'
}

// Bulk action types
export interface BulkActionRequest {
  action: string
  ids: Array<number | string>
}

// Export types
export type ExportFormat = 'csv' | 'json' | 'xlsx'
