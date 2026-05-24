import { test } from '@playwright/test'
import path from 'node:path'

const outDir = path.resolve(import.meta.dirname, '../screenshots/proto')

test.use({ viewport: { width: 1600, height: 1100 }, deviceScaleFactor: 2 })

test('referential page', async ({ page }) => {
  const logs: string[] = []
  page.on('console', (msg) => logs.push(`[${msg.type()}] ${msg.text()}`))
  page.on('pageerror', (err) => logs.push(`[PAGEERROR] ${err.message}`))

  await page.goto('http://localhost:5173/referential', { waitUntil: 'networkidle' })
  await page.waitForTimeout(2000)

  await page.screenshot({ path: path.join(outDir, 'referential-default.png'), fullPage: true })

  // Click BCE-only tab
  const bceTab = page.locator('button', { hasText: 'BCE-only' })
  if (await bceTab.count()) {
    await bceTab.click()
    await page.waitForTimeout(300)
    await page.screenshot({ path: path.join(outDir, 'referential-bce-only.png'), fullPage: true })
  }

  console.log('=== BROWSER LOGS ===')
  for (const l of logs.slice(-20)) console.log(l)
})
