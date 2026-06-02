import { defineConfig } from '@playwright/test'

// Config de la capture parité PROTO (proto.ts uniquement).
// Le proto Vue est servi en DIST : build figé → vite preview → capture →
// teardown auto. Source de vérité déterministe (pas de HMR, pas de
// transform-on-demand). `proto:dev` (5174) reste pour l'audit humain ;
// ce serveur (4174) est dédié à la capture. Viewport phone défini dans proto.ts.
export default defineConfig({
  testDir: './capture',
  testMatch: 'proto.ts',
  timeout: 30000,
  webServer: {
    command: 'pnpm -C ../proto build && pnpm -C ../proto preview --port 4174 --strictPort',
    url: 'http://localhost:4174/',
    timeout: 180_000,
    reuseExistingServer: false,
    stdout: 'pipe',
    stderr: 'pipe',
  },
})
