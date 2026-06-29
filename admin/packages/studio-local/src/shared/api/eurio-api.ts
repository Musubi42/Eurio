/**
 * Client `eurio-api` — auth-adapter local (PAT) / hébergé (cookie OIDC). (Model B / R1)
 *
 * UN seul codebase, deux modes pilotés par `AUTH_MODE` (cf. `shared/config/deploy-target`) :
 *  - `pat` (local) : le PAT vit dans `.env.local` (gitignored) sous `VITE_EURIO_PAT`, injecté
 *    en header `Authorization: Bearer`. Pas de cookie : cross-origin localhost → VPS, le cookie
 *    SameSite=Lax ne traverse pas.
 *  - `cookie` (hébergé) : `credentials: 'include'` envoie le cookie HttpOnly `eurio_session`
 *    posé par eurio-api après le flow Authentik. Pas de header auth, pas de PAT requis.
 *
 * Spec : docs/work-in-progress/model-b/README.md §Front.
 */
import { AUTH_MODE } from '@/shared/config/deploy-target'

const API_BASE: string =
  (import.meta.env.VITE_EURIO_API_BASE as string | undefined)?.trim() ||
  'https://eurio-api.musubi.dev'

const PAT: string =
  (import.meta.env.VITE_EURIO_PAT as string | undefined)?.trim() ?? ''

export class EurioApiError extends Error {
  status: number
  body: unknown
  constructor(status: number, body: unknown, message: string) {
    super(message)
    this.status = status
    this.body = body
  }
}

export class MissingPatError extends Error {
  constructor() {
    super(
      'VITE_EURIO_PAT manquant — voir admin/packages/studio-local/.env.example',
    )
  }
}

function authHeader(): Record<string, string> {
  // Mode cookie : aucun header auth (le cookie part via credentials:'include').
  if (AUTH_MODE === 'cookie') return {}
  if (!PAT) throw new MissingPatError()
  return { Authorization: `Bearer ${PAT}` }
}

/**
 * Auth « présente » côté front : en mode PAT, vrai si un PAT est configuré ; en mode
 * cookie, toujours vrai (la validité réelle est vérifiée par `/me`, pas connaissable ici).
 */
export function hasPat(): boolean {
  return AUTH_MODE === 'cookie' ? true : Boolean(PAT)
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  opts?: { keepalive?: boolean },
): Promise<T> {
  const headers: Record<string, string> = { ...authHeader() }
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    // Mode cookie : envoie le cookie de session HttpOnly cross-origin.
    credentials: AUTH_MODE === 'cookie' ? 'include' : 'same-origin',
    body: body !== undefined ? JSON.stringify(body) : undefined,
    // `keepalive` : le POST survit à un unload de page (fenêtre d'undo review).
    keepalive: opts?.keepalive,
  })

  let parsed: unknown = null
  const text = await res.text()
  if (text) {
    try {
      parsed = JSON.parse(text)
    } catch {
      parsed = text
    }
  }

  if (!res.ok) {
    const detail =
      (parsed && typeof parsed === 'object' && 'detail' in parsed
        ? String((parsed as { detail: unknown }).detail)
        : null) ?? res.statusText
    throw new EurioApiError(
      res.status,
      parsed,
      `${method} ${path}: ${res.status} ${detail}`,
    )
  }
  return parsed as T
}

export const eurioApi = {
  base: API_BASE,
  hasPat,
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown, opts?: { keepalive?: boolean }) =>
    request<T>('POST', path, body, opts),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, body),
  delete: <T>(path: string) => request<T>('DELETE', path),
}
