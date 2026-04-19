import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './capture',
  testMatch: '*.ts',
  timeout: 30000,
  use: {
    baseURL: 'http://localhost:5173',
    viewport: { width: 800, height: 1100 },
    deviceScaleFactor: 2,
  },
})
