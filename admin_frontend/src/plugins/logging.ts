import type { App } from 'vue'
import type { AdminPlugin, ModelConfig } from '@/types/admin'

const LoggingPlugin: AdminPlugin = {
  name: 'Logging',
  version: '1.0.0',

  install(app: App) {
    app.config.globalProperties.$logAction = (action: string, details?: any) => {
      console.log(`[Admin Action] ${action}`, details || '')
    }
  },

  hooks: {
    onModelLoad(config: ModelConfig) {
      console.log(`[Logging Plugin] Model loaded: ${config.name}`)
    },

    onBeforeSave(model: string, data: any) {
      console.log(`[Logging Plugin] Before save: ${model}`, data)
      return data
    },

    onAfterSave(model: string, data: any) {
      console.log(`[Logging Plugin] After save: ${model}`, data)
    },

    onBeforeDelete(model: string, id: string | number) {
      console.log(`[Logging Plugin] Before delete: ${model}#${id}`)
      return true
    },
  },
}

export default LoggingPlugin
