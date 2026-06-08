import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// Front régie reviewers, servi par review_service sous /admin (VPS).
// base '/admin/' → les assets du build sont référencés en /admin/assets/...
// L'API est sur la même origine (chemins relatifs) → VITE_REVIEW_API='' en
// prod ; en dev local on pointe le service review sur :8048.
export default defineConfig({
  base: '/admin/',
  plugins: [vue()],
  server: { port: 5181 },
  define: {
    'import.meta.env.VITE_REVIEW_API': JSON.stringify(
      process.env.VITE_REVIEW_API ?? 'http://localhost:8048',
    ),
  },
})
