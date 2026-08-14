import path from 'node:path'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'

// Proto Eurio — PWA Vue qui consomme le contrat `api/` (fixtures | live).
// Web app installable (pas d'embed iPhone) : on l'héberge et on y accède au tel.
// tokens.css depuis @shared (R2) ; components/shell/coin-detail CSS dans le package.
export default defineConfig({
  plugins: [
    vue(),
    VitePWA({
      registerType: 'autoUpdate',
      // SW en build uniquement : le dev reste non-caché pour l'audit live.
      devOptions: { enabled: false },
      includeAssets: ['icons/favicon-64.png', 'icons/icon.svg', 'data/app_core.json'],
      manifest: {
        name: 'Eurio',
        short_name: 'Eurio',
        description: 'Collection de pièces euro — scan-first.',
        lang: 'fr',
        start_url: '/',
        scope: '/',
        display: 'standalone',
        orientation: 'portrait',
        background_color: '#0B0B1A',
        theme_color: '#1A1B4B',
        icons: [
          { src: 'icons/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any maskable' },
          { src: 'icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any maskable' },
          { src: 'icons/icon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any' },
        ],
      },
      workbox: {
        // app_core.json fait 2.5 Mo → on relève le plafond de précache.
        maximumFileSizeToCacheInBytes: 4 * 1024 * 1024,
        globPatterns: ['**/*.{js,css,html,svg,png,webp,woff2,json}'],
      },
    }),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      // Tokens canoniques (R2 : shared/tokens.css, jamais édités côté proto).
      // `@shared` (alias vers ../../../shared) retiré le 2026-08-14 : les tokens
      // et fixtures passent par le package workspace `@eurio/shared` (ADR-007).
    },
  },
  server: {
    host: true, // expose sur le réseau local → test direct au téléphone
    port: 5174,
    strictPort: true, // ne jamais voler le port d'un autre paquet (web = 5173) → échoue clairement
  },
  preview: {
    port: 5174,
    strictPort: true,
  },
})
