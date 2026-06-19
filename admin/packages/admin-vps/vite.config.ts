import path from 'node:path'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// Vite 6 ne propage pas automatiquement les vars shell vers import.meta.env.
// On lit depuis process.env (peuplé par direnv) et on injecte via define.
// Aucun fichier .env tracké — source unique = secrets/dev.env (SOPS).
const PUBLIC_VITE_PREFIX = 'VITE_'
const publicEnv = Object.fromEntries(
  Object.entries(process.env)
    .filter(([k]) => k.startsWith(PUBLIC_VITE_PREFIX))
    .map(([k, v]) => [`import.meta.env.${k}`, JSON.stringify(v)]),
)

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
      // tokens.css partagé avec le proto et l'app Android
      '@shared': path.resolve(__dirname, '../../../shared'),
    },
  },
  define: {
    ...publicEnv,
    // defaults (peuvent être overridés via env)
    'import.meta.env.VITE_EURIO_API_BASE': JSON.stringify(
      process.env.VITE_EURIO_API_BASE || 'http://localhost:8042',
    ),
    'import.meta.env.VITE_EURIO_DEV_BYPASS': JSON.stringify(
      process.env.VITE_EURIO_DEV_BYPASS || '0',
    ),
  },
  server: {
    port: 5173,
    strictPort: true,
    host: '127.0.0.1',
  },
  build: {
    target: 'es2022',
    sourcemap: true,
  },
})
