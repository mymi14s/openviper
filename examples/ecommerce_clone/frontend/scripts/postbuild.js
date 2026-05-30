#!/usr/bin/env node
/**
 * Post-build script: copies React build artifacts to the
 * templates/ and static/ directories one level up from frontend/.
 *
 * Mapping:
 *   build/index.html          → ../templates/index.html
 *   build/static/             → ../static/
 *   build/asset-manifest.json → ../static/asset-manifest.json
 *   build/*.{ico,png,txt,…}   → ../static/
 */

const fs = require('fs');
const path = require('path');

const buildDir = path.resolve(__dirname, '..', 'build');
const root = path.resolve(__dirname, '..', '..');
const templatesDir = path.join(root, 'templates');
const staticDir = path.join(root, 'static');

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function copyFile(src, dest) {
  ensureDir(path.dirname(dest));
  fs.copyFileSync(src, dest);
  console.log(`  copied  ${path.relative(root, src)}  →  ${path.relative(root, dest)}`);
}

function copyDir(src, dest) {
  ensureDir(dest);
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      copyDir(srcPath, destPath);
    } else {
      copyFile(srcPath, destPath);
    }
  }
}

console.log('\n📦 Post-build: copying assets...\n');

// 1. index.html → templates/index.html
copyFile(path.join(buildDir, 'index.html'), path.join(templatesDir, 'index.html'));

// 2. build/static/ → static/
const buildStatic = path.join(buildDir, 'static');
if (fs.existsSync(buildStatic)) {
  copyDir(buildStatic, staticDir);
}

// 3. asset-manifest.json → static/asset-manifest.json
const manifest = path.join(buildDir, 'asset-manifest.json');
if (fs.existsSync(manifest)) {
  copyFile(manifest, path.join(staticDir, 'asset-manifest.json'));
}

// 4. Any other root-level build files (favicon, robots.txt, manifest.json, *.png, etc.)
//    that aren't index.html or the static/ folder
for (const entry of fs.readdirSync(buildDir, { withFileTypes: true })) {
  if (entry.isFile() && entry.name !== 'index.html' && entry.name !== 'asset-manifest.json') {
    copyFile(path.join(buildDir, entry.name), path.join(staticDir, entry.name));
  }
}

console.log('\n✅ Done.\n');
