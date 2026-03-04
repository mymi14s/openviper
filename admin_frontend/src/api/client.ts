import axios, { AxiosInstance, AxiosError, InternalAxiosRequestConfig } from 'axios'
import { useAuthStore } from '@/stores/auth'
import type {
  ApiResponse,
  LoginRequest,
  LoginResponse,
  ModelConfig,
  ModelField,
  ModelInstance,
  PaginatedResponse,
  ChangeHistoryEntry,
  DashboardStats,
  BulkActionRequest,
  ExportFormat,
  AdminConfig
} from '@/types/admin'

const API_BASE = '/admin/api'

// Create axios instance
const client: AxiosInstance = axios.create({
  baseURL: API_BASE,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor - add auth token
client.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const authStore = useAuthStore()
    if (authStore.token) {
      config.headers.Authorization = `Bearer ${authStore.token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// Response interceptor - handle errors
client.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiResponse>) => {
    if (error.response?.status === 401 || error.response?.status === 403) {
      // Only redirect if we are NOT already on the login page.
      // Redirecting during a login attempt causes a full page reload
      // and hides the error message from the user.
      const isLoginPage = window.location.pathname.replace(/\/$/, '').endsWith('/login')
      const isLoginRequest = error.config?.url?.includes('/auth/login')
      if (!isLoginPage && !isLoginRequest) {
        const authStore = useAuthStore()
        authStore.clearAuth()
        window.location.href = '/admin/login'
      }
    }
    return Promise.reject(error)
  }
)

export const authApi = {
  async login(credentials: LoginRequest): Promise<LoginResponse> {
    const response = await client.post<LoginResponse>('/auth/login/', credentials)
    return response.data
  },

  async logout(): Promise<void> {
    await client.post('/auth/logout/')
  },

  async getCurrentUser(): Promise<LoginResponse['user']> {
    const response = await client.get('/auth/me/')
    return response.data
  },

  async refreshToken(): Promise<{ token: string; expires_at: string }> {
    const response = await client.post('/auth/refresh/')
    return response.data
  },

  async changePassword(data: {
    current_password: string
    new_password: string
    confirm_password: string
  }): Promise<void> {
    await client.post('/auth/change-password/', data)
  },

  async changeUserPassword(userId: number | string, data: {
    new_password: string
    confirm_password: string
  }): Promise<void> {
    await client.post(`/ auth / change - user - password / ${userId}/`, data)
  },
}

function transformField(name: string, field: Record<string, unknown>): ModelField {
  const config = (field.config ?? {}) as Record<string, unknown>
  return {
    name: (field.name as string) || name,
    type: (field.type as string) || 'text',
    label: (field.name as string) || name,
    required: (config.required as boolean) ?? !(field.null as boolean),
    readonly: (config.readonly as boolean) ?? false,
    help_text: (config.help_text as string) || '',
    choices: (config.choices as ModelField['choices']) || (field.choices as ModelField['choices']) || undefined,
    default: field.default,
    max_length: (config.max_length as number) || (field.max_length as number),
    min_value: (config.min as number) || (field.min_value as number),
    max_value: (config.max as number) || (field.max_value as number),
    related_model: field.related_model as string | undefined,
    component: (field.component as string) || 'text',
  }
}

function transformModelFields(model: Record<string, unknown>): ModelConfig {
  if (model.fields && !Array.isArray(model.fields)) {
    model.fields = Object.entries(model.fields as Record<string, unknown>).map(
      ([name, field]) => transformField(name, field as Record<string, unknown>)
    )
  }
  // Transform each child table's fields dict so ChildTable.vue gets proper ModelField objects
  if (Array.isArray(model.child_tables)) {
    for (const ct of model.child_tables as Record<string, unknown>[]) {
      if (ct.fields && typeof ct.fields === 'object' && !Array.isArray(ct.fields)) {
        const raw = ct.fields as Record<string, unknown>
        const transformed: Record<string, ModelField> = {}
        for (const [name, field] of Object.entries(raw)) {
          transformed[name] = transformField(name, field as Record<string, unknown>)
        }
        ct.fields = transformed
      }
    }
  }
  return model as unknown as ModelConfig
}

export const modelsApi = {
  async getModels(): Promise<ModelConfig[]> {
    const response = await client.get<{ models: any[]; apps: any[] }>('/models/')
    return response.data.models.map(transformModelFields)
  },

  async getModel(appLabel: string, modelName: string): Promise<ModelConfig> {
    const response = await client.get<any>(`/models/${appLabel}/${modelName}/`)
    return transformModelFields(response.data)
  },

  async getModelList(
    appLabel: string,
    modelName: string,
    params: {
      page?: number
      per_page?: number
      search?: string
      ordering?: string
      filters?: Record<string, any>
    } = {}
  ): Promise<PaginatedResponse<ModelInstance>> {
    const response = await client.get<PaginatedResponse<ModelInstance>>(
      `/models/${appLabel}/${modelName}/list/`,
      { params }
    )
    return response.data
  },

  async getModelInstance(
    appLabel: string,
    modelName: string,
    id: string | number
  ): Promise<ModelInstance> {
    const response = await client.get<{ instance: ModelInstance }>(
      `/models/${appLabel}/${modelName}/${id}/`
    )
    return response.data.instance
  },

  async createModelInstance(
    appLabel: string,
    modelName: string,
    data: Record<string, any>
  ): Promise<ModelInstance> {
    const response = await client.post<ModelInstance>(
      `/models/${appLabel}/${modelName}/`,
      data
    )
    return response.data
  },

  async updateModelInstance(
    appLabel: string,
    modelName: string,
    id: string | number,
    data: Record<string, any>
  ): Promise<ModelInstance> {
    const response = await client.put<ModelInstance>(
      `/models/${appLabel}/${modelName}/${id}/`,
      data
    )
    return response.data
  },

  async deleteModelInstance(
    appLabel: string,
    modelName: string,
    id: string | number
  ): Promise<void> {
    await client.delete(`/models/${appLabel}/${modelName}/${id}/`)
  },

  async bulkAction(
    appLabel: string,
    modelName: string,
    action: BulkActionRequest
  ): Promise<{ success: boolean; affected: number }> {
    const response = await client.post(
      `/models/${appLabel}/${modelName}/bulk-action/`,
      action
    )
    return response.data
  },

  async exportData(
    appLabel: string,
    modelName: string,
    format: ExportFormat,
    ids?: Array<string | number>
  ): Promise<Blob> {
    const response = await client.get(
      `/models/${appLabel}/${modelName}/export/`,
      {
        params: { format, ids: ids?.join(',') },
        responseType: 'blob',
      }
    )
    return response.data
  },

  async getFieldChoices(
    appLabel: string,
    modelName: string,
    fieldName: string
  ): Promise<Array<{ value: any; label: string }>> {
    const response = await client.get(
      `/models/${appLabel}/${modelName}/field-choices/${fieldName}/`
    )
    return response.data
  },

  async searchForeignKey(
    appLabel: string,
    modelName: string,
    query: string,
    limit: number = 20
  ): Promise<Array<{ value: any; label: string }>> {
    const response = await client.get(
      `/models/${appLabel}/${modelName}/fk-search/`,
      { params: { q: query, limit } }
    )
    return response.data.items
  },
}

export const dashboardApi = {
  async getConfig(): Promise<AdminConfig> {
    const response = await client.get<AdminConfig>('/config/')
    return response.data
  },

  async getStats(): Promise<DashboardStats> {
    const response = await client.get<DashboardStats>('/dashboard/')
    return response.data
  },

  async getRecentActivity(limit: number = 10): Promise<ChangeHistoryEntry[]> {
    const response = await client.get<ChangeHistoryEntry[]>('/activity/', {
      params: { limit },
    })
    return response.data
  },
}

export const historyApi = {
  async getHistory(
    appLabel: string,
    modelName: string,
    objectId: string | number
  ): Promise<ChangeHistoryEntry[]> {
    const response = await client.get<{ history: ChangeHistoryEntry[] }>(
      `/models/${appLabel}/${modelName}/${objectId}/history/`
    )
    return response.data.history
  },

  async revertChange(historyId: number): Promise<ModelInstance> {
    const response = await client.post<ModelInstance>(
      `/history/${historyId}/revert/`
    )
    return response.data
  },
}

export const searchApi = {
  async globalSearch(query: string): Promise<{
    results: Array<{
      app_label: string
      model_name: string
      id: string | number
      display: string
      score: number
    }>
  }> {
    const response = await client.get('/search/', { params: { q: query } })
    return response.data
  },
}

export default client
