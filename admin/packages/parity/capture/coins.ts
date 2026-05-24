import { test } from '@playwright/test'
import path from 'node:path'

const outDir = path.resolve(import.meta.dirname, '../screenshots/proto')

test.use({ viewport: { width: 1600, height: 1100 }, deviceScaleFactor: 2 })

test('coins page', async ({ page }) => {
  const logs: string[] = []
  page.on('console', (msg) => logs.push(`[${msg.type()}] ${msg.text()}`))
  page.on('pageerror', (err) => logs.push(`[PAGEERROR] ${err.message}`))

  await page.goto('http://localhost:5173/coins', { waitUntil: 'networkidle' })
  await page.waitForTimeout(3000)  // let lazy images settle

  await page.screenshot({ path: path.join(outDir, 'coins-after-chunk-a.png'), fullPage: false })

  console.log('=== BROWSER LOGS (image 4xx will appear here) ===')
  for (const l of logs.slice(-20)) console.log(l)
})
