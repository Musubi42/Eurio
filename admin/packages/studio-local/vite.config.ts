import fs from 'node:fs'
import path from 'node:path'
import vue from '@vitejs/plugin-vue'
import yaml from 'js-yaml'
import { defineConfig } from 'vite'
import type { Plugin } from 'vite'

// Vite expose déjà les vars shell préfixées VITE_ (process.env, peuplé par
// direnv) vers import.meta.env — dont VITE_EURIO_PAT (aliasé sur
// EURIO_API_TOKEN par .envrc). Le `define` ci-dessous n'est qu'un
// belt-and-suspenders pour 2 vars de build spécifiques ; zéro .env file requis.

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
  const maestroFlows = path.resolve(__dirname, '../parity/flows')
  const maestroScreenshots = path.resolve(__dirname, '../parity/screenshots/android')
  const mlDatasets = path.resolve(__dirname, '../../../ml/datasets')
  const protoScreenshots = path.resolve(__dirname, '../parity/screenshots/proto')
  const repoRoot = path.resolve(__dirname, '../../../')

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

        if (req.url?.startsWith('/screenshots/proto/')) {
          const file = path.join(protoScreenshots, path.basename(req.url))
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

        // Serve shared/ assets from repo root.
        //
        // ⚠️ VESTIGE (2026-08-14). Motif d'origine : le CSS du proto faisait
        // `@import '../../../../shared/tokens.css'`, résolu en URL /shared/tokens.css.
        // Ce n'est plus le cas — le proto passe par le package `@eurio/shared`
        // (ADR-007) et plus aucune source ni aucun bundle ne demande /shared/.
        // Conservé par prudence : le viewer de parité n'a pas pu être testé lors
        // du changement. À SUPPRIMER dès qu'une session vérifie que
        // `go-task parity:*` fonctionne sans lui.
        if (req.url?.startsWith('/shared/')) {
          const relPath = req.url.split('?')[0].split('#')[0]
          const filePath = path.join(repoRoot, relPath)
          if (!filePath.startsWith(repoRoot)) {
            res.statusCode = 403
            res.end('Forbidden')
            return
          }
          try {
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

        // Le proto Vue n'est plus servi par la console web : il a son propre
        // dev server (admin/packages/proto, port 5174) et sa capture parité
        // tourne contre son build dist (cf. parity/playwright.proto.config.ts).

        next()
      })
    },
  }
}

export default defineConfig({
  plugins: [vue(), devMiddleware()],
  // Port explicite + strictPort : web reste sur 5173, ne vole jamais le 5174 du proto.
  server: { port: 5173, strictPort: true },
  preview: { port: 5173, strictPort: true },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  define: {
    // R1 — build hébergé : VITE_DEPLOY_TARGET + VITE_EURIO_API_BASE arrivent par
    // build-arg Docker (process.env). En local ils viennent de `.env.local` (dotenv
    // Vite) → on n'injecte ici QUE s'ils sont présents dans l'env shell, sinon on
    // écraserait la valeur `.env.local` par une chaîne vide.
    ...(process.env.VITE_DEPLOY_TARGET
      ? {
          'import.meta.env.VITE_DEPLOY_TARGET':
            JSON.stringify(process.env.VITE_DEPLOY_TARGET),
        }
      : {}),
    ...(process.env.VITE_EURIO_API_BASE
      ? {
          'import.meta.env.VITE_EURIO_API_BASE':
            JSON.stringify(process.env.VITE_EURIO_API_BASE),
        }
      : {}),
  },
})
