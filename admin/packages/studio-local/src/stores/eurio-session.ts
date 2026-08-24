/**
 * Pinia store — Principal courant côté studio-local (via PAT Bearer).
 *
 * Au boot, on appelle `/me`. Si pas de PAT ou PAT invalide → status="missing"
 * ou "invalid", l'UI affiche un bandeau d'avertissement + lien vers
 * `PAT-WORKFLOW.md`. Le store reste utilisable côté code mais isAuthed=false.
 *
 * eurio-api est la seule source auth + data côté front : l'auth Supabase OTP
 * (F5) et le client data Supabase (D7) ont été retirés. Tout passe par
 * `eurioApi.*` + `useEurioSession`.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import {
  EurioApiError,
  MissingPatError,
  eurioApi,
  hasPat,
} from '@/shared/api/eurio-api'
import { AUTH_MODE } from '@/shared/config/deploy-target'
import { OIDC_TRIED_KEY, startOidcLogin } from '@/shared/auth/oidc'

// Garde anti-boucle : on ne redirige vers Authentik qu'UNE fois par session de tab.
// Si on revient encore non-authentifié, on s'arrête sur le bandeau (login manuel).
// La clé vit dans `shared/auth/oidc` : `oidcLogout` l'arme aussi, pour que la
// déconnexion ne soit pas défaite par un auto-login silencieux au retour.

export interface Principal {
  user_id: string
  email: string
  name: string
  roles: string[]
  scopes: string[]
  auth_method: 'oidc' | 'api_token'
}

type Status = 'idle' | 'loading' | 'ok' | 'missing' | 'invalid' | 'error'

export const useEurioSession = defineStore('eurio-session', () => {
  const principal = ref<Principal | null>(null)
  const status = ref<Status>('idle')
  const error = ref<string | null>(null)

  const isAuthed = computed(() => principal.value !== null)
  const scopes = computed(() => new Set(principal.value?.scopes ?? []))
  const roles = computed(() => new Set(principal.value?.roles ?? []))

  function hasScope(s: string): boolean {
    return scopes.value.has(s)
  }
  function hasRole(r: string): boolean {
    return roles.value.has(r)
  }

  async function load(): Promise<void> {
    // Mode PAT : pas de PAT configuré → "missing" (bandeau). Mode cookie :
    // `hasPat()` est toujours vrai → on tente `/me`, un 401 (pas de cookie / session
    // expirée) bascule en "invalid".
    if (!hasPat()) {
      status.value = 'missing'
      principal.value = null
      return
    }
    status.value = 'loading'
    error.value = null
    try {
      principal.value = await eurioApi.get<Principal>('/me')
      status.value = 'ok'
      // Login OK → on réarme la possibilité d'un futur auto-login.
      try { sessionStorage.removeItem(OIDC_TRIED_KEY) } catch { /* SSR/privacy */ }
    } catch (e) {
      principal.value = null
      if (e instanceof MissingPatError) {
        status.value = 'missing'
      } else if (e instanceof EurioApiError && (e.status === 401 || e.status === 403)) {
        status.value = 'invalid'
        if (AUTH_MODE === 'cookie') {
          // Pas de cookie valide → tente le login OIDC UNE fois (SSO silencieux si une
          // session Authentik est déjà active). Si on revient encore 401, garde
          // anti-boucle : on reste sur le bandeau avec le bouton « Se connecter ».
          let tried = false
          try { tried = sessionStorage.getItem(OIDC_TRIED_KEY) === '1' } catch { /* ignore */ }
          if (!tried) {
            try { sessionStorage.setItem(OIDC_TRIED_KEY, '1') } catch { /* ignore */ }
            startOidcLogin()
            return
          }
          error.value = 'Connexion Authentik échouée ou refusée — réessaie, ou contacte un admin.'
        } else {
          error.value = 'PAT invalide ou expiré — régénère EURIO_API_TOKEN dans secrets/dev.env (`go-task secrets:edit`), puis `direnv reload` + relance `go-task front:dev`.'
        }
      } else {
        status.value = 'error'
        error.value = e instanceof Error ? e.message : String(e)
      }
    }
  }

  return {
    principal,
    status,
    error,
    isAuthed,
    hasScope,
    hasRole,
    load,
  }
})
