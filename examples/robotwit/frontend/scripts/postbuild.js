#!/usr/bin/env node

import { copyFileSync, cpSync, existsSync, mkdirSync, readdirSync } from 'fs'
import { dirname, join, resolve } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))

const buildDir = resolve(__dirname, '..', 'build')
const root = resolve(__dirname, '..', '..')
const templatesDir = join(root, 'templates')
const staticDir = join(root, 'static')

function ensureDir(dir) {
  mkdirSync(dir, { recursive: true })
}

function copyFile(src, dest) {
  ensureDir(dirname(dest))
  copyFileSync(src, dest)
  console.log(`  copied  ${resolve(root, src)}  ->  ${resolve(root, dest)}`)
}

function copyDir(src, dest) {
  ensureDir(dest)
  for (const entry of readdirSync(src, { withFileTypes: true })) {
    const srcPath = join(src, entry.name)
    const destPath = join(dest, entry.name)
    if (entry.isDirectory()) {
      copyDir(srcPath, destPath)
    } else {
      copyFile(srcPath, destPath)
    }
  }
}

console.log('Post-build: copying artifacts...')

if (existsSync(join(buildDir, 'index.html'))) {
  copyFile(join(buildDir, 'index.html'), join(templatesDir, 'index.html'))
}

const buildStatic = join(buildDir, 'assets')
if (existsSync(buildStatic)) {
  copyDir(buildStatic, join(staticDir, 'assets'))
}

for (const file of readdirSync(buildDir)) {
  if (file !== 'index.html' && file !== 'assets' && !file.startsWith('.')) {
    copyFile(join(buildDir, file), join(staticDir, file))
  }
}

console.log('Post-build complete.')
