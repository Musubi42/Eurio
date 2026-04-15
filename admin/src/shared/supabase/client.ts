import { createClient } from '@supabase/supabase-js'
import type { Database } from './types'

const url = import.meta.env.VITE_SUPABASE_URL
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

if (!url || !anonKey) {
  throw new Error(
    'Variables d\'environnement manquantes.\n' +
    'Ajouter dans .envrc :\n' +
    '  export VITE_SUPABASE_URL=...\n' +
    '  export VITE_SUPABASE_ANON_KEY=...\n' +
    'Puis : direnv allow'
  )
}

// En dev local, si VITE_SUPABASE_SERVICE_KEY est défini,
// on crée un client avec la service key qui bypass RLS et auth.
// La service key ne sort JAMAIS de .envrc (gitignore) et n'est jamais bundlée en prod
// (import.meta.env.DEV est false au build Vite → tree-shaked).
const serviceKey = import.meta.env.VITE_SUPABASE_SERVICE_KEY

export const DEV_BYPASS = import.meta.env.DEV && !!serviceKey

export const supabase = createClient<Database>(
  url,
  DEV_BYPASS ? serviceKey : anonKey,
  {
    auth: {
      autoRefreshToken: !DEV_BYPASS,
      persistSession: !DEV_BYPASS,
      detectSessionInUrl: !DEV_BYPASS,
    },
  },
)
