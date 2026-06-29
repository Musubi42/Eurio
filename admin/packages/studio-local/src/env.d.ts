/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SUPABASE_URL: string
  readonly VITE_SUPABASE_ANON_KEY: string
  readonly VITE_SUPABASE_SERVICE_KEY?: string
  /** Base URL de l'API canonique VPS (eurio-api FastAPI). */
  readonly VITE_EURIO_API_BASE?: string
  /** PAT personnel pour studio-local — format `eurio_<43 chars base64url>`. */
  readonly VITE_EURIO_PAT?: string
  /** URL du ML API local (go-task ml:api). Défaut : http://127.0.0.1:8042 */
  readonly VITE_ML_API?: string
  /**
   * Cible de déploiement (Model B / R1). `local` (défaut) = poste dev, auth PAT,
   * features lourdes ML actives. `hosted` = panel VPS, auth cookie OIDC, features
   * lourdes grisées. Pilote l'auth-adapter ET la baseline `hasLocalMlApi`.
   */
  readonly VITE_DEPLOY_TARGET?: 'local' | 'hosted'
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

// Vue SFC type resolution
declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<object, object, unknown>
  export default component
}
