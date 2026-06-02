import { test } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import yaml from 'js-yaml'

// Capture parité — proto Vue servi en DIST (cf. webServer playwright.config.ts).
// Déterministe par construction : build figé, pas de HMR ni transform-on-demand.
// Routing = createWebHashHistory → URL `/#<route>` ; on pilote via window.__eurio
// (reset / seed / goto) plutôt que par query, pour coller au contrat des flows.
const PROTO_BASE = 'http://localhost:4174'

declare global {
  interface Window {
    __eurio?: {
      reset: () => void
      goto: (path: string) => void
      seed: (name: string) => void
    }
    __eurioHas3D?: boolean
    __eurioCoinReady?: boolean
  }
}

interface FlowConfig {
  appId?: string
  env?: Record<string, string>
}

interface Scene {
  id: string
  route: string
  state: string | null
}

const flowsDir = path.resolve(import.meta.dirname, '../flows')
const outDir = path.resolve(import.meta.dirname, '../screenshots/proto')

function loadScenes(): Scene[] {
  const files = fs.readdirSync(flowsDir).filter(f => f.endsWith('.yaml'))
  const scenes: Scene[] = []

  for (const file of files) {
    const content = fs.readFileSync(path.join(flowsDir, file), 'utf-8')
    const docs: unknown[] = []
    yaml.loadAll(content, (doc: unknown) => docs.push(doc))

    const config = docs[0] as FlowConfig | undefined
    const env = config?.env ?? {}
    const route = env.PARITY_PROTO_ROUTE
    if (!route) continue

    scenes.push({
      id: env.PARITY_ID ?? file.replace('.yaml', ''),
      route,
      state: env.PARITY_STATE ?? null,
    })
  }

  return scenes
}

const scenes = loadScenes()

// Viewport téléphone : `.screen` est max-width 440 × 100dvh → on capture le
// device entier. DPR 3 pour une définition cohérente avec les captures Android.
test.use({ viewport: { width: 430, height: 932 }, deviceScaleFactor: 3 })

for (const scene of scenes) {
  test(`capture ${scene.id}`, async ({ page }) => {
    // 0. Mode parité (horloge figée) AVANT boot — cf. proto/src/api/parity.ts.
    await page.addInitScript(() => {
      ;(window as Window & { __eurioParity?: boolean }).__eurioParity = true
    })

    // 1. Charger l'app à la racine et attendre que le hook de test soit prêt.
    await page.goto(`${PROTO_BASE}/`, { waitUntil: 'load' })
    await page.waitForFunction(
      () => typeof window.__eurio?.goto === 'function',
      null,
      { timeout: 15000 },
    )

    // 2. Appliquer l'état nommé (PARITY_STATE) puis naviguer via le routeur.
    await page.evaluate(({ route, state }) => {
      if (state) window.__eurio!.seed(state)
      else window.__eurio!.reset()
      window.__eurio!.goto(route)
    }, { route: scene.route, state: scene.state })

    // 3. Attendre le montage de la scène. Si elle contient un canvas 3D, attendre
    //    le signal `__eurioCoinReady` (coin posé + texture uploadée au GPU) plutôt
    //    qu'un délai aveugle → capture 3D déterministe (zéro race texture/clip).
    await page.waitForFunction(() => {
      const s = document.querySelector('.screen')
      if (!s || s.children.length === 0) return false
      // Fonts chargées (sinon 1er run à froid = rendu texte différent → flake).
      if (document.fonts && document.fonts.status !== 'loaded') return false
      // Scènes 3D coin uniquement (marqueur explicite, pas « tout canvas » — la
      // carte à gratter a aussi un canvas) : attendre le coin posé + texturé.
      if (window.__eurioHas3D) return window.__eurioCoinReady === true
      return true
    }, null, { timeout: 12000 })

    // Settle court : paint final. Coin 3D prêt + fonts chargées (cf. ci-dessus).
    await page.waitForTimeout(500)

    // 4. Capturer le device (`.screen`) via clip — overflow:hidden empêche
    //    element.screenshot() (« element not visible »).
    const box = await page.locator('.screen').boundingBox()
    await page.screenshot({
      path: path.join(outDir, `${scene.id}.png`),
      ...(box ? { clip: box } : {}),
    })
  })
}
