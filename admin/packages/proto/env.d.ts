/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Source de données : 'fixtures' (app_core.json local) | 'live' (Supabase). */
  readonly VITE_DATA_MODE?: 'fixtures' | 'live'
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<Record<string, unknown>, Record<string, unknown>, unknown>
  export default component
}
