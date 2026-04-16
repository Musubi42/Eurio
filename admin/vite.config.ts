import fs from 'node:fs'
import path from 'node:path'
import vue from '@vitejs/plugin-vue'
import yaml from 'js-yaml'
import { defineConfig } from 'vite'
import type { Plugin } from 'vite'

// Vite 6 ne propage pas automatiquement les vars shell vers import.meta.env.
// On lit depuis process.env (peuplé par direnv) et on injecte via define.
// Les valeurs viennent de .envrc (gitignore) — zéro .env file.

interface MaestroConfig {
  appId?: string
  env?: Record<string, string>
}

interface ManifestEntry {
  id: string
  label: string
  group: string
  phase: number | null
  protoRoute: string | null
  captures: string[]
  status: 'captured' | 'partial' | 'pending'
  state: string | null
}

function parseMaestroFlows(flowsDir: string, screenshotsDir: string): ManifestEntry[] {
  if (!fs.existsSync(flowsDir)) return []

  const files = fs.readdirSync(flowsDir).filter(f => f.endsWith('.yaml'))
  const entries: ManifestEntry[] = []

  for (const file of files) {
    const content = fs.readFileSync(path.join(flowsDir, file), 'utf-8')
    const docs: unknown[] = []
    yaml.loadAll(content, (doc: unknown) => docs.push(doc))

    const config = docs[0] as MaestroConfig | undefined
    const commands = (docs[1] as unknown[]) ?? []
    const env = config?.env ?? {}

    const captures = commands
      .filter((cmd): cmd is { takeScreenshot: string } =>
        typeof cmd === 'object' && cmd !== null && 'takeScreenshot' in cmd,
      )
      .map(cmd => cmd.takeScreenshot)

    const capturedCount = captures.filter(name =>
      fs.existsSync(path.join(screenshotsDir, `${name}.png`)),
    ).length

    entries.push({
      id: env.PARITY_ID ?? file.replace('.yaml', ''),
      label: env.PARITY_LABEL ?? file.replace('.yaml', ''),
      group: env.PARITY_GROUP ?? 'Uncategorized',
      phase: env.PARITY_PHASE ? parseInt(env.PARITY_PHASE, 10) : null,
      protoRoute: env.PARITY_PROTO_ROUTE ?? null,
      captures,
      status:
        capturedCount === 0
          ? 'pending'
          : capturedCount === captures.length
            ? 'captured'
            : 'partial',
      state: env.PARITY_STATE ?? null,
    })
  }

  return entries
}

const MIME_TYPES: Record<string, string> = {
  '.html': 'text/html',
  '.css': 'text/css',
  '.js': 'application/javascript',
  '.mjs': 'application/javascript',
  '.json': 'application/json',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.woff2': 'font/woff2',
  '.woff': 'font/woff',
  '.ttf': 'font/ttf',
}

function devMiddleware(): Plugin {
  const maestroFlows = path.resolve(__dirname, '../maestro/flows')
  const maestroScreenshots = path.resolve(__dirname, '../maestro/screenshots')
  const mlDatasets = path.resolve(__dirname, '../ml/datasets')
  const protoRoot = path.resolve(__dirname, '../docs/design/prototype')

  return {
    name: 'dev-middleware',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url === '/arbitrage-queue.json') {
          try {
            const data = fs.readFileSync(path.join(mlDatasets, 'numista_review_queue.json'), 'utf-8')
            res.setHeader('Content-Type', 'application/json')
            res.end(data)
          } catch {
            res.statusCode = 404
            res.end('Not found')
          }
          return
        }

        if (req.url === '/scene-mapping.json') {
          const manifest = parseMaestroFlows(maestroFlows, maestroScreenshots)
          res.setHeader('Content-Type', 'application/json')
          res.end(JSON.stringify(manifest))
          return
        }

        if (req.url?.startsWith('/screenshots/')) {
          const file = path.join(maestroScreenshots, path.basename(req.url))
          try {
            const data = fs.readFileSync(file)
            res.setHeader('Content-Type', 'image/png')
            res.end(data)
          } catch {
            res.statusCode = 404
            res.end('Not found')
          }
          return
        }

        // Serve proto HTML/CSS/JS directly — replaces the Python proxy.
        // No-cache headers prevent stale ES modules in the parity viewer iframe.
        if (req.url?.startsWith('/proto/')) {
          let relPath = req.url.slice('/proto'.length)
          // Strip hash/query for filesystem lookup
          relPath = relPath.split('?')[0].split('#')[0]
          if (relPath === '/' || relPath === '') relPath = '/index.html'

          const filePath = path.join(protoRoot, relPath)
          // Prevent directory traversal
          if (!filePath.startsWith(protoRoot)) {
            res.statusCode = 403
            res.end('Forbidden')
            return
          }

          try {
            // Follow symlinks (fixtures symlink)
            const stat = fs.statSync(filePath)
            if (stat.isDirectory()) {
              // Try index.html in directory
              const indexPath = path.join(filePath, 'index.html')
              if (fs.existsSync(indexPath)) {
                const data = fs.readFileSync(indexPath)
                res.setHeader('Content-Type', 'text/html')
                res.setHeader('Cache-Control', 'no-cache, no-store, must-revalidate')
                res.end(data)
                return
              }
            }
            const data = fs.readFileSync(filePath)
            const ext = path.extname(filePath).toLowerCase()
            res.setHeader('Content-Type', MIME_TYPES[ext] ?? 'application/octet-stream')
            res.setHeader('Cache-Control', 'no-cache, no-store, must-revalidate')
            res.end(data)
          } catch {
            res.statusCode = 404
            res.end('Not found')
          }
          return
        }

        next()
      })
    },
  }
}

export default defineConfig({
  plugins: [vue(), devMiddleware()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  define: {
    'import.meta.env.VITE_SUPABASE_URL':
      JSON.stringify(process.env.VITE_SUPABASE_URL ?? ''),
    'import.meta.env.VITE_SUPABASE_ANON_KEY':
      JSON.stringify(process.env.VITE_SUPABASE_ANON_KEY ?? ''),
    // Optionnel — bypass dev local (service_role key depuis .envrc)
    'import.meta.env.VITE_SUPABASE_SERVICE_KEY':
      JSON.stringify(process.env.VITE_SUPABASE_SERVICE_KEY ?? ''),
  },
})
