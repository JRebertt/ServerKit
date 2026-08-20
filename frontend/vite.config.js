/* global process */
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'url'
import { VENDOR_IMPORTMAP } from './src/plugins/runtime/vendorManifest.js'

// Runtime-extension import map (plan 25 Decision 2). A runtime-loaded extension
// bundle externalizes exactly these bare specifiers and resolves them at load
// time to the panel's own singleton instances via the `/serverkit-vendor/*.mjs`
// shims (fed by src/plugins/runtime/vendorShare.js). Injected into index.html at
// BUILD time only: Vite's dev server does its own bare-specifier resolution, and
// runtime loading is a production concern (dev uses the build-time glob path).
// The map is inert for the host's own code (bundled to hashed relative chunks,
// never bare specifiers) — it only affects the extension blobs.
// Sourced from the ONE vendor manifest, so the import map, the shims under
// public/serverkit-vendor/ and vendorShare's namespace capture cannot drift
// apart. They previously did: two mapped specifiers had no shim at all.

function serverkitImportmap() {
    return {
        name: 'serverkit-vendor-importmap',
        apply: 'build',
        transformIndexHtml() {
            return [{
                tag: 'script',
                attrs: { type: 'importmap' },
                children: JSON.stringify(VENDOR_IMPORTMAP),
                injectTo: 'head-prepend',
            }]
        },
    }
}

export default defineConfig(({ mode }) => {
    const env = loadEnv(mode, process.cwd(), '')
    const frontendPort = Number(env.SERVERKIT_FRONTEND_PORT) || 41921
    const apiTarget = (env.VITE_API_URL || 'http://localhost:47927/api/v1').replace(/\/api\/v1\/?$/, '')

    const rawAllowedHosts = (env.VITE_ALLOWED_HOSTS || '').trim()
    let allowedHosts
    if (rawAllowedHosts === 'all') {
        allowedHosts = true
    } else if (rawAllowedHosts) {
        allowedHosts = rawAllowedHosts.split(',').map(s => s.trim()).filter(Boolean)
    }

    return {
        plugins: [react(), serverkitImportmap()],
        resolve: {
            alias: {
                '@': fileURLToPath(new URL('./src', import.meta.url)),
                // Stable import path for plugin code:
                //   import { api, useAuth } from 'serverkit-sdk';
                // Internal restructures of src/plugins/sdk are invisible
                // to plugins as long as the named exports stay stable.
                'serverkit-sdk': fileURLToPath(new URL('./src/plugins/sdk/index.js', import.meta.url)),
            },
            // Force every `react` / `react-dom` / `react-router-dom`
            // import (host code AND plugin code loaded via
            // import.meta.glob) to resolve to one copy. Without this
            // Vite can hand plugins a different React instance if dep
            // optimization runs mid-session, producing the
            // "Invalid hook call / ReactCurrentDispatcher is null"
            // crash inside the contributions hook.
            //
            // Do NOT add resolve.alias entries for these — aliasing to
            // the package directory bypasses Vite's optimizeDeps and
            // serves raw ESM, which (combined with pre-bundled
            // react-dom) recreates the same two-copies problem from the
            // other direction.
            // i18next/react-i18next join the list for the same reason: two
            // instances means an extension's t() reads an uninitialised store
            // and silently renders English forever (plan 79).
            dedupe: ['react', 'react-dom', 'react-router-dom', 'i18next', 'react-i18next'],
        },
        optimizeDeps: {
            // Pre-bundle the renderer at server start instead of
            // discovering it lazily. Lazy discovery is what triggers the
            // mid-session re-bundle that strands the open browser tab
            // on a stale React URL.
            include: ['react', 'react-dom', 'react-router-dom', 'i18next', 'react-i18next'],
        },
        server: {
            port: frontendPort,
            ...(allowedHosts !== undefined ? { allowedHosts } : {}),
            proxy: {
                '/api': {
                    target: apiTarget,
                    changeOrigin: true,
                },
                '/socket.io': {
                    target: apiTarget,
                    changeOrigin: true,
                    ws: true,
                },
            },
            // Enable polling for WSL (Windows filesystem doesn't support inotify)
            watch: {
                usePolling: true,
                interval: 1000,
            },
        },
        css: {
            preprocessorOptions: {
                scss: {
                    // Silence Dart Sass deprecation warnings for @import and slash-div
                    // These are expected during migration from LESS and will be addressed
                    // when moving to @use/@forward module system
                    silenceDeprecations: ['import', 'slash-div', 'legacy-js-api', 'global-builtin', 'color-functions', 'strict-unary'],
                },
            },
        },
        build: {
            sourcemap: false,
            rollupOptions: {
                output: {
                    // Vite 8 bundles with rolldown, which only accepts the
                    // FUNCTION form of manualChunks (the object form that
                    // Rollup allowed throws "manualChunks is not a function").
                    // Match on node_modules path so each listed package — plus
                    // its private deps — lands in one cohesive vendor chunk.
                    // Anything unmatched falls through to Vite's default
                    // chunking, so shared deps (e.g. d3 used by both charts and
                    // flow) get their own common chunk instead of duplicating.
                    manualChunks(id) {
                        if (!id.includes('node_modules')) return
                        if (/[\\/]node_modules[\\/](react|react-dom|react-router|react-router-dom|@remix-run[\\/]router|scheduler)[\\/]/.test(id)) return 'vendor-react'
                        if (/[\\/]node_modules[\\/]recharts[\\/]/.test(id)) return 'vendor-charts'
                        if (/[\\/]node_modules[\\/]@xyflow[\\/]/.test(id)) return 'vendor-flow'
                        if (/[\\/]node_modules[\\/]@xterm[\\/]/.test(id)) return 'vendor-xterm'
                        if (/[\\/]node_modules[\\/]lucide-react[\\/]/.test(id)) return 'vendor-icons'
                    },
                },
            },
        },
    }
})
