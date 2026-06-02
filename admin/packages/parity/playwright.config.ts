import { defineConfig } from '@playwright/test'

// Config des captures ADMIN (referential / coins / operations) : pages de la
// console web servies par le dev server admin (localhost:5173, lancé à la main).
// La capture parité proto a sa propre config (playwright.proto.config.ts) avec
// son webServer dist dédié — découplées pour qu'une capture admin ne builde
// jamais le proto, et inversement.
export default defineConfig({
  testDir: './capture',
  testMatch: ['referential.ts', 'coins.ts', 'operations.ts'],
  timeout: 30000,
  use: {
    baseURL: 'http://localhost:5173',
    viewport: { width: 800, height: 1100 },
    deviceScaleFactor: 2,
  },
})
