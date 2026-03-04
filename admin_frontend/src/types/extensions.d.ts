import type { AdminExtension, AdminRegistry, ExtensionContext } from '@/plugins/extensionLoader'

declare global {
  interface Window {
    /**
     * Global admin extension registry.
     *
     * Read current state synchronously at any time:
     * ```js
     * window.__adminRegistry.currentObject  // null | object
     * window.__adminRegistry.currentList    // object[]
     * window.__adminRegistry.currentModel   // null | model config
     * ```
     *
     * Explicit registration (advanced / backward compat):
     * ```js
     * window.__adminRegistry.register({
     *   id: 'my-extension',
     *   onRoute(path, params) { ... },
     *   onObject(object, model, params) { ... },
     *   onList(items, model, params) { ... },
     * })
     * ```
     */
    __adminRegistry: AdminRegistry

    /**
     * Mutable context object injected by the loader before each extension
     * file is executed.  Just assign the hooks you need — nothing else
     * required.  The loader auto-registers them after the file runs.
     *
     * ```js
     * // my_app/admin_extensions/index.js
     * __ext.onObject = function (object, model, params) { ... }
     * __ext.onList   = function (items,  model, params) { ... }
     * __ext.onRoute  = function (path,   params)        { ... }
     * ```
     *
     * Set to `null` between extension loads.
     */
    __ext: ExtensionContext | null
  }
}

export type { AdminExtension, AdminRegistry, ExtensionContext }
