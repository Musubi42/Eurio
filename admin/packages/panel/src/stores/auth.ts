/**
 * Auth store — charge `/me` au boot, expose le Principal courant et les
 * helpers `hasScope`/`hasRole` pour les guards de router + le filtrage de nav.
 *
 * Le cookie `eurio_session` est HttpOnly — le panel ne le voit jamais et ne
 * peut pas le décoder. La source de vérité = `/me`, appelée au boot et après
 * chaque login/logout.
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

import { api, ApiError } from '@/api/client'

export interface Principal {
  user_id: string
  email: string
  name: string
  roles: string[]
  scopes: string[]
  auth_method: 'oidc' | 'api_token'
}

export const useAuthStore = defineStore('auth', () => {
  const principal = ref<Principal | null>(null)
  const loading = ref(true)
  const loaded = ref(false)
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
    loading.value = true
    error.value = null
    try {
      principal.value = await api.get<Principal>('/me')
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        principal.value = null
      } else {
        error.value = e instanceof Error ? e.message : String(e)
        principal.value = null
      }
    } finally {
      loading.value = false
      loaded.value = true
    }
  }

  function login(returnTo?: string): void {
    const target = encodeURIComponent(returnTo ?? window.location.href)
    window.location.href = `${api.base}/auth/oidc/login?return_to=${target}`
  }

  function devLogin(email = 'dev@local.test'): void {
    window.location.href = `${api.base}/auth/oidc/dev/login?email=${encodeURIComponent(email)}`
  }

  async function logout(): Promise<void> {
    try {
      await api.post('/auth/oidc/logout')
    } catch {
      // best-effort — on continue même si le cookie est déjà invalide
    }
    principal.value = null
  }

  return {
    principal,
    loading,
    loaded,
    error,
    isAuthed,
    hasScope,
    hasRole,
    load,
    login,
    devLogin,
    logout,
  }
})
