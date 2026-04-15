import path from 'node:path'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// Vite 6 ne propage pas automatiquement les vars shell vers import.meta.env.
// On lit depuis process.env (peuplé par direnv) et on injecte via define.
// Les valeurs viennent de .envrc (gitignore) — zéro .env file.

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  define: {
    'import.meta.env.VITE_SUPABASE_URL':
      JSON.stringify(process.env.VITE_SUPABASE_URL ?? ''),
    'import.meta.env.VITE_SUPABASE_ANON_KEY':
      JSON.stringify(process.env.VITE_SUPABASE_ANON_KEY ?? ''),
    // Optionnel — bypass dev local (service_role key depuis .envrc)
    'import.meta.env.VITE_SUPABASE_SERVICE_KEY':
      JSON.stringify(process.env.VITE_SUPABASE_SERVICE_KEY ?? ''),
  },
})
