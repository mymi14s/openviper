import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import { readFileSync, writeFileSync } from 'fs'

function rewriteAdminPaths(): import('vite').Plugin {
  return {
    name: 'rewrite-admin-paths',
    closeBundle() {
      const indexPath = resolve(__dirname, '../openviper/admin/static/admin/index.html')
      const content = readFileSync(indexPath, 'utf-8')
      writeFileSync(indexPath, content.replaceAll('/admin/', '/static/admin/'))
    },
  }
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [vue(), rewriteAdminPaths()],
  base: '/admin/',
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 3001,
    proxy: {
      '/admin/api': {
        target: 'http://localhost:8765',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: '../openviper/admin/static/admin/',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['vue', 'vue-router', 'pinia', 'axios'],
          charts: ['chart.js', 'vue-chartjs'],
        },
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/__tests__/setup.ts'],
    include: ['src/__tests__/**/*.test.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      include: ['src/**/*.{ts,vue}'],
      exclude: ['src/main.ts', 'src/**/*.d.ts', 'src/__tests__/**'],
    },
  },
})
