import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// Front reviewer minimal (amis non-techniques), servi depuis le VPS.
// Pas de .env : VITE_REVIEW_API vient de l'env shell (direnv) via define,
// comme admin/packages/web. Défaut local : le service review sur :8048.
export default defineConfig({
  plugins: [vue()],
  server: { port: 5180 },
  define: {
    'import.meta.env.VITE_REVIEW_API': JSON.stringify(
      process.env.VITE_REVIEW_API ?? 'http://localhost:8048',
    ),
  },
})
