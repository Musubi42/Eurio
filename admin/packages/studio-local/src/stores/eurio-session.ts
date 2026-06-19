/**
 * Pinia store — Principal courant côté studio-local (via PAT Bearer).
 *
 * Au boot, on appelle `/me`. Si pas de PAT ou PAT invalide → status="missing"
 * ou "invalid", l'UI affiche un bandeau d'avertissement + lien vers
 * `PAT-WORKFLOW.md`. Le store reste utilisable côté code mais isAuthed=false.
 *
 * NOTE : ce store coexiste pour l'instant avec l'auth Supabase historique
 * (LoginPage OTP + AuthCallbackPage). Le port complet "rip Supabase auth,
 * use eurio-api only" est planifié en chunk suivant. Pour l'instant : tout
 * appel à eurio-api passe par `eurioApi.*` + `useEurioSession`, et l'accès
 * Supabase data continue normalement.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import {
  EurioApiError,
  MissingPatError,
  eurioApi,
  hasPat,
} from '@/shared/api/eurio-api'

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
    } catch (e) {
      principal.value = null
      if (e instanceof MissingPatError) {
        status.value = 'missing'
      } else if (e instanceof EurioApiError && (e.status === 401 || e.status === 403)) {
        status.value = 'invalid'
        error.value = 'PAT invalide ou expiré — régénère depuis admin-vps et MAJ .env.local.'
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
