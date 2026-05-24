import { test } from '@playwright/test'
import path from 'node:path'

const outDir = path.resolve(import.meta.dirname, '../screenshots/proto')

test.use({ viewport: { width: 1600, height: 1100 }, deviceScaleFactor: 2 })

test('operations dashboard', async ({ page }) => {
  const logs: string[] = []
  page.on('console', (msg) => logs.push(`[${msg.type()}] ${msg.text()}`))
  page.on('pageerror', (err) => logs.push(`[PAGEERROR] ${err.message}`))

  await page.goto('http://localhost:5173/operations', { waitUntil: 'networkidle' })
  await page.waitForTimeout(2000)

  // Each section as its own crop (hi-res)
  const sections = ['Pulse eBay', 'Training readiness', 'Diversité wild', 'Bench cohort']
  for (let i = 0; i < sections.length; i++) {
    const sec = page.locator('section').nth(i)
    if (await sec.count()) {
      await sec.screenshot({ path: path.join(outDir, `operations-${i + 1}.png`) })
    }
  }

  // Top-of-page (header + pulse) hi-res
  await page.screenshot({ path: path.join(outDir, 'operations-top.png'), fullPage: false })

  console.log('=== BROWSER LOGS ===')
  for (const l of logs) console.log(l)
})
