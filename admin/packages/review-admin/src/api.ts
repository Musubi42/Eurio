// Client des routes /admin/* du service review. Le token admin
// (REVIEW_ADMIN_TOKEN) est gardé en localStorage et envoyé en header
// X-Admin-Token. Un 401 vide le token (re-login). Même origine en prod
// (chemins relatifs), :8048 en dev.

const API = import.meta.env.VITE_REVIEW_API || ''
const TOKEN_KEY = 'er_admin_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

export class AuthError extends Error {}

export interface Reviewer {
  token: string
  display_name: string
  is_active: boolean
  created_at: string
  last_seen_at: string | null
  total: number
  last7: number
  in_flight: number
  invite_url: string
}

export interface Flow {
  pending: number
  awaiting_reconcile: number
  last_publish_at: string | null
  last_reconcile_at: string | null
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken()
  const resp = await fetch(`${API}${path}`, {
    ...init,
    headers: { ...(init?.headers ?? {}), 'X-Admin-Token': token ?? '' },
  })
  if (resp.status === 401) {
    clearToken()
    throw new AuthError('Token admin invalide')
  }
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({ detail: `HTTP ${resp.status}` }))
    throw new Error(
      body && typeof body === 'object' && 'detail' in body
        ? String((body as { detail: unknown }).detail)
        : `HTTP ${resp.status}`,
    )
  }
  if (resp.status === 204) return undefined as T
  return (await resp.json()) as T
}

function postJson<T>(path: string, body: unknown): Promise<T> {
  return req<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export const api = {
  flow: () => req<Flow>('/admin/flow'),
  listReviewers: () => req<{ reviewers: Reviewer[] }>('/admin/reviewers'),
  createReviewer: (token: string, name: string) =>
    postJson<{ token: string; name: string; invite_url: string }>('/admin/reviewers', {
      token,
      name,
    }),
  revokeReviewer: (token: string) =>
    req<{ token: string; is_active: boolean }>(`/admin/reviewers/${encodeURIComponent(token)}`, {
      method: 'DELETE',
    }),
  reactivateReviewer: (token: string) =>
    postJson<{ token: string; is_active: boolean }>(
      `/admin/reviewers/${encodeURIComponent(token)}/reactivate`,
      {},
    ),
}
