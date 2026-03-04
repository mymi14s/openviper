/**
 * Admin extension loader.
 *
 * Drop a `.js` or `.vue` file into any installed app's `admin_extensions/`
 * folder and it is loaded automatically — no registration boilerplate needed.
 *
 *   my_app/
 *     admin_extensions/
 *       index.js    ← plain JS, zero boilerplate
 *       MyComp.vue  ← compiled Vue component (needs project build step)
 *
 * ─────────────────────────────────────────────────────────────────────
 * ZERO-BOILERPLATE API  (recommended)
 * ─────────────────────────────────────────────────────────────────────
 * The loader injects a `__ext` context object before running each file.
 * Just assign the hooks you need — nothing else required:
 *
 *   // my_app/admin_extensions/index.js
 *
 *   // Detail / edit page  →  called whenever the object is loaded
 *   __ext.onObject = function (object, model, params) {
 *     // object  – the raw model instance  { id, username, email, … }
 *     // model   – model config  { verbose_name, fields, permissions, … }
 *     // params  – route params  { appLabel, modelName, id }
 *   }
 *
 *   // List page  →  called whenever rows are loaded
 *   __ext.onList = function (items, model, params) {
 *     // items   – array of model instances
 *     // model   – model config
 *     // params  – route params  { appLabel, modelName }
 *   }
 *
 *   // Every navigation
 *   __ext.onRoute = function (path, params) { … }
 *
 * ─────────────────────────────────────────────────────────────────────
 * READ CURRENT DATA ANYWHERE (sync)
 * ─────────────────────────────────────────────────────────────────────
 *   window.__adminRegistry.currentObject   // detail object  | null
 *   window.__adminRegistry.currentList     // list rows      | []
 *   window.__adminRegistry.currentModel    // model config   | null
 *
 * ─────────────────────────────────────────────────────────────────────
 * ADVANCED: explicit registration (backward-compat / multiple hooks)
 * ─────────────────────────────────────────────────────────────────────
 *   window.__adminRegistry.register({
 *     id: 'my-extension',
 *     onObject(object, model, params) { … },
 *     onList(items, model, params) { … },
 *     onRoute(path, params) { … },
 *   })
 */

import { createApp } from 'vue'
import * as Vue from 'vue'

// ─── Types ────────────────────────────────────────────────────────────────────

export interface AdminExtension {
  id: string
  onRoute?:  (path: string, params: Record<string, string>) => void
  onObject?: (object: Record<string, any>, model: Record<string, any>, params: Record<string, string>) => void
  onList?:   (items: Record<string, any>[], model: Record<string, any>, params: Record<string, string>) => void
}

/** Mutable context object exposed as `window.__ext` before each file runs. */
export interface ExtensionContext {
  /** Auto-set by the loader — the app name + file slug. */
  id: string
  onRoute?:  AdminExtension['onRoute']
  onObject?: AdminExtension['onObject']
  onList?:   AdminExtension['onList']
}

export interface AdminRegistry {
  /** Explicitly register an extension (backward compat / advanced use). */
  register(extension: AdminExtension): void
  getAll(): AdminExtension[]

  notifyRoute(path: string, params: Record<string, string>): void
  notifyObject(object: Record<string, any> | null, model: Record<string, any> | null, params: Record<string, string>): void
  notifyList(items: Record<string, any>[], model: Record<string, any> | null, params: Record<string, string>): void

  readonly currentObject: Record<string, any> | null
  readonly currentList:   Record<string, any>[]
  readonly currentModel:  Record<string, any> | null
}

// ─── Registry ─────────────────────────────────────────────────────────────────

function createRegistry(): AdminRegistry {
  const extensions: AdminExtension[] = []

  let _currentObject: Record<string, any> | null = null
  let _currentList:   Record<string, any>[]       = []
  let _currentModel:  Record<string, any> | null  = null

  const registry: AdminRegistry = {
    register(ext) {
      if (!ext.id) return
      const idx = extensions.findIndex((e) => e.id === ext.id)
      if (idx >= 0) { extensions[idx] = ext } else { extensions.push(ext) }
      console.debug(`[admin-ext] registered: ${ext.id}`)
    },
    getAll() { return [...extensions] },

    notifyRoute(path, params) {
      for (const ext of extensions) {
        try { ext.onRoute?.(path, params) }
        catch (err) { console.error(`[admin-ext] "${ext.id}" onRoute error:`, err) }
      }
    },

    notifyObject(object, model, params) {
      _currentObject = object
      _currentModel  = model
      if (!object) return
      for (const ext of extensions) {
        try { ext.onObject?.(object, model ?? {}, params) }
        catch (err) { console.error(`[admin-ext] "${ext.id}" onObject error:`, err) }
      }
    },

    notifyList(items, model, params) {
      _currentList  = items
      _currentModel = model
      for (const ext of extensions) {
        try { ext.onList?.(items, model ?? {}, params) }
        catch (err) { console.error(`[admin-ext] "${ext.id}" onList error:`, err) }
      }
    },

    get currentObject() { return _currentObject },
    get currentList()   { return _currentList },
    get currentModel()  { return _currentModel },
  }

  return registry
}

// ─── Script injection ─────────────────────────────────────────────────────────

/**
 * Inject a classic `<script>` tag.
 * Before injection we set `window.__ext` so the file can assign hooks
 * without any boilerplate.  After the script executes we auto-register
 * whatever was placed on `window.__ext`.
 */
function injectScript(url: string, extId: string): Promise<void> {
  return new Promise((resolve, reject) => {
    if (document.querySelector(`script[data-admin-ext="${url}"]`)) {
      resolve()
      return
    }

    // Expose the mutable context the script will write into
    const ctx: ExtensionContext = { id: extId }
    ;(window as any).__ext = ctx

    const script = document.createElement('script')
    script.src = url
    script.dataset.adminExt = url

    script.onload = () => {
      // Auto-register any hooks the script assigned to __ext
      const filled = (window as any).__ext as ExtensionContext
      if (filled && (filled.onObject || filled.onList || filled.onRoute)) {
        window.__adminRegistry.register({
          id:       filled.id,
          onObject: filled.onObject,
          onList:   filled.onList,
          onRoute:  filled.onRoute,
        })
      }
      // Clean up the shared slot so the next extension starts fresh
      ;(window as any).__ext = null
      resolve()
    }

    script.onerror = () => {
      ;(window as any).__ext = null
      reject(new Error(`Failed to load extension: ${url}`))
    }

    document.head.appendChild(script)
  })
}

/**
 * Load a `.vue` Single-File Component using vue3-sfc-loader (runtime compiler).
 * The SFC receives `extId` as a root prop and self-registers its hooks with
 * the registry inside `onMounted()` — no `window.__ext` boilerplate needed.
 *
 * For any other ES module file the old `window.__ext` context pattern is used.
 */
async function injectModule(url: string, extId: string): Promise<void> {
  if (document.querySelector(`[data-admin-ext="${url}"]`)) return

  if (url.endsWith('.vue')) {
    // ── Vue SFC ── runtime-compile via vue3-sfc-loader ──────────────────
    const { loadModule } = await import('vue3-sfc-loader')

    const Component = await loadModule(url, {
      moduleCache: { vue: Vue as any },
      async getFile(fileUrl: string) {
        const res = await fetch(fileUrl)
        if (!res.ok) throw new Error(`[admin-ext] fetch failed: ${fileUrl}`)
        return res.text()
      },
      addStyle(css: string) {
        const style = document.createElement('style')
        style.textContent = css
        document.head.appendChild(style)
      },
    } as any)

    // Mount into a non-visible host element; the SFC uses <Teleport> for UI
    const host = document.createElement('div')
    host.dataset.adminExt = url
    host.dataset.adminExtId = extId
    document.body.appendChild(host)
    createApp(Component as Parameters<typeof createApp>[0], { extId }).mount(host)

  } else {
    // ── Generic ESM ── use window.__ext context pattern ─────────────────
    const ctx: ExtensionContext = { id: extId }
    ;(window as any).__ext = ctx

    try {
      await import(/* @vite-ignore */ url)
      const filled = (window as any).__ext as ExtensionContext
      if (filled && (filled.onObject || filled.onList || filled.onRoute)) {
        window.__adminRegistry.register({
          id:       filled.id,
          onObject: filled.onObject,
          onList:   filled.onList,
          onRoute:  filled.onRoute,
        })
      }
    } finally {
      ;(window as any).__ext = null
      const marker = document.createElement('script')
      marker.dataset.adminExt = url
      marker.type = 'text/placeholder'
      document.head.appendChild(marker)
    }
  }
}

// ─── Manifest loader ──────────────────────────────────────────────────────────

/**
 * Fetch the extension manifest and load every listed file.
 * Files are loaded sequentially so `__ext` is never shared between two scripts.
 */
export async function loadExtensions(): Promise<void> {
  try {
    const res = await fetch('/admin/api/extensions/')
    if (!res.ok) {
      console.warn('[admin-ext] manifest fetch failed:', res.status)
      return
    }

    const data: { extensions: { app: string; file: string; url: string; type: string }[] } = await res.json()

    for (const entry of data.extensions) {
      const extId = `${entry.app}::${entry.file.replace(/\.[^.]+$/, '')}`
      try {
        if (entry.type === 'module') {
          await injectModule(entry.url, extId)
        } else {
          await injectScript(entry.url, extId)
        }
        console.debug(`[admin-ext] loaded ${entry.app}/${entry.file}`)
      } catch (err) {
        console.error(`[admin-ext] error loading ${entry.app}/${entry.file}:`, err)
      }
    }
  } catch (err) {
    console.error('[admin-ext] failed to load extensions:', err)
  }
}

// ─── Bootstrap ────────────────────────────────────────────────────────────────

if (!(window as any).__adminRegistry) {
  ;(window as any).__adminRegistry = createRegistry()
}

