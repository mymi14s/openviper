import type { App } from 'vue'
import type { AdminPlugin, ModelConfig } from '@/types/admin'

// Plugin registry
const plugins: Map<string, AdminPlugin> = new Map()

// Plugin hooks
const hooks = {
  onModelLoad: [] as Array<(config: ModelConfig) => void>,
  onBeforeSave: [] as Array<(model: string, data: any) => any>,
  onAfterSave: [] as Array<(model: string, data: any) => void>,
  onBeforeDelete: [] as Array<(model: string, id: string | number) => boolean>,
}

/**
 * Register a plugin
 */
export function registerPlugin(plugin: AdminPlugin): void {
  if (plugins.has(plugin.name)) {
    console.warn(`Plugin "${plugin.name}" is already registered`)
    return
  }

  plugins.set(plugin.name, plugin)

  // Register hooks
  if (plugin.hooks) {
    if (plugin.hooks.onModelLoad) {
      hooks.onModelLoad.push(plugin.hooks.onModelLoad)
    }
    if (plugin.hooks.onBeforeSave) {
      hooks.onBeforeSave.push(plugin.hooks.onBeforeSave)
    }
    if (plugin.hooks.onAfterSave) {
      hooks.onAfterSave.push(plugin.hooks.onAfterSave)
    }
    if (plugin.hooks.onBeforeDelete) {
      hooks.onBeforeDelete.push(plugin.hooks.onBeforeDelete)
    }
  }

  console.log(`Plugin "${plugin.name}" v${plugin.version} registered`)
}

/**
 * Install plugins into Vue app
 */
export function installPlugins(app: App, pluginList: AdminPlugin[]): void {
  for (const plugin of pluginList) {
    registerPlugin(plugin)
    plugin.install(app)

    // Register custom components
    if (plugin.components) {
      for (const [name, component] of Object.entries(plugin.components)) {
        app.component(`Plugin${plugin.name}${name}`, component)
      }
    }
  }
}

/**
 * Get a registered plugin
 */
export function getPlugin(name: string): AdminPlugin | undefined {
  return plugins.get(name)
}

/**
 * Get all registered plugins
 */
export function getAllPlugins(): AdminPlugin[] {
  return Array.from(plugins.values())
}

/**
 * Run onModelLoad hooks
 */
export function runOnModelLoad(config: ModelConfig): void {
  for (const hook of hooks.onModelLoad) {
    try {
      hook(config)
    } catch (error) {
      console.error('Plugin onModelLoad hook error:', error)
    }
  }
}

/**
 * Run onBeforeSave hooks
 * Returns the potentially modified data
 */
export function runOnBeforeSave(model: string, data: any): any {
  let result = data
  for (const hook of hooks.onBeforeSave) {
    try {
      result = hook(model, result) ?? result
    } catch (error) {
      console.error('Plugin onBeforeSave hook error:', error)
    }
  }
  return result
}

/**
 * Run onAfterSave hooks
 */
export function runOnAfterSave(model: string, data: any): void {
  for (const hook of hooks.onAfterSave) {
    try {
      hook(model, data)
    } catch (error) {
      console.error('Plugin onAfterSave hook error:', error)
    }
  }
}

/**
 * Run onBeforeDelete hooks
 * Returns false if any hook prevents deletion
 */
export function runOnBeforeDelete(model: string, id: string | number): boolean {
  for (const hook of hooks.onBeforeDelete) {
    try {
      if (hook(model, id) === false) {
        return false
      }
    } catch (error) {
      console.error('Plugin onBeforeDelete hook error:', error)
    }
  }
  return true
}

/**
 * Get all plugin routes
 */
export function getPluginRoutes(): any[] {
  const routes: any[] = []
  for (const plugin of plugins.values()) {
    if (plugin.routes) {
      routes.push(...plugin.routes)
    }
  }
  return routes
}
