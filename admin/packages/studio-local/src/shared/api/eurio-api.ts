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

/** Une requête qui n'a pas répondu dans le délai imparti. Distincte d'une
 *  `EurioApiError` : le serveur n'a rien dit, on ne sait pas s'il a agi. */
export class EurioApiTimeout extends Error {
  constructor(method: string, path: string, ms: number) {
    super(`${method} ${path} : aucune réponse après ${Math.round(ms / 1000)} s`)
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

/**
 * Plafond de patience, en millisecondes.
 *
 * `fetch()` nu n'expire JAMAIS : une API qui pend laisse l'écran sur son
 * spinner indéfiniment, et l'utilisateur ne peut pas distinguer « ça calcule »
 * de « c'est mort ». C'est ce qui faisait attendre cinq minutes devant la modale
 * de recadrage. Un délai dépassé n'est pas une opinion sur la lenteur du
 * serveur : c'est la seule façon de rendre la main.
 *
 * 30 s parce que les lectures nominales sont à p90 = 0,17 s (mesuré le
 * 2026-08-24 sur 40 `crop-edit-context`) : ce plafond ne coupe rien de sain.
 * Les appels qui ont besoin de plus le disent par `opts.timeoutMs`.
 */
const DEFAULT_TIMEOUT_MS = 30_000

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  opts?: { keepalive?: boolean; signal?: AbortSignal; timeoutMs?: number },
): Promise<T> {
  const headers: Record<string, string> = { ...authHeader() }
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  // Deux causes d'abandon, un seul signal : le plafond de patience, et
  // l'annulation demandée par l'appelant (l'écran a changé, la modale s'est
  // refermée). On distingue les deux au rejet — un timeout mérite un message,
  // une annulation volontaire ne mérite rien du tout.
  const budget = opts?.timeoutMs ?? DEFAULT_TIMEOUT_MS
  const ctrl = new AbortController()
  let timedOut = false
  const timer = setTimeout(() => {
    timedOut = true
    ctrl.abort()
  }, budget)
  const onExternalAbort = () => ctrl.abort()
  // Un signal DÉJÀ avorté ne redispatche pas son évènement : sans ce test, une
  // requête annulée avant même d'être lancée partait quand même sur le réseau.
  if (opts?.signal?.aborted) ctrl.abort()
  else opts?.signal?.addEventListener('abort', onExternalAbort, { once: true })

  // Le budget couvre AUSSI la lecture du corps : `fetch` résout dès les
  // en-têtes, et un flux qui s'arrête en cours de route pendrait tout autant.
  let res: Response
  let text: string
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      // Mode cookie : envoie le cookie de session HttpOnly cross-origin.
      credentials: AUTH_MODE === 'cookie' ? 'include' : 'same-origin',
      body: body !== undefined ? JSON.stringify(body) : undefined,
      // `keepalive` : le POST survit à un unload de page (fenêtre d'undo review).
      keepalive: opts?.keepalive,
      signal: ctrl.signal,
    })
    text = await res.text()
  } catch (err) {
    if (timedOut) throw new EurioApiTimeout(method, path, budget)
    throw err
  } finally {
    clearTimeout(timer)
    opts?.signal?.removeEventListener('abort', onExternalAbort)
  }

  let parsed: unknown = null
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
  get: <T>(path: string, opts?: { signal?: AbortSignal; timeoutMs?: number }) =>
    request<T>('GET', path, undefined, opts),
  post: <T>(
    path: string,
    body?: unknown,
    opts?: { keepalive?: boolean; signal?: AbortSignal; timeoutMs?: number },
  ) => request<T>('POST', path, body, opts),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, body),
  delete: <T>(path: string) => request<T>('DELETE', path),
}
