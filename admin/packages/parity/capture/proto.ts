import { test } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import yaml from 'js-yaml'

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

for (const scene of scenes) {
  test(`capture ${scene.id}`, async ({ page }) => {
    // Navigate to the scene with optional state preset
    const hash = scene.state
      ? `${scene.route}?state=${scene.state}`
      : scene.route

    await page.goto(`/proto/index.html#${hash}`, {
      waitUntil: 'networkidle',
    })

    // Wait for the proto router to mount the scene (content appears in #view)
    await page.waitForFunction(() => {
      const view = document.querySelector('#view')
      return view && view.children.length > 0
    }, { timeout: 10000 })

    // Extra settle time for async renders (coin SVGs, data loading, fonts)
    await page.waitForTimeout(1500)

    // Find the .screen element and capture it via clip coordinates.
    // Using clip instead of element.screenshot() avoids Playwright's
    // "element not visible" check which fails for overflow:hidden containers.
    const screenBox = await page.locator('.screen').boundingBox()
    if (screenBox) {
      await page.screenshot({
        path: path.join(outDir, `${scene.id}.png`),
        clip: screenBox,
      })
    } else {
      // Fallback: full page screenshot
      await page.screenshot({
        path: path.join(outDir, `${scene.id}.png`),
      })
    }
  })
}
