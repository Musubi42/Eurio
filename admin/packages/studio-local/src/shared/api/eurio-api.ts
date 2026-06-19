/**
 * Client `eurio-api` pour studio-local — Bearer PAT.
 *
 * Le PAT vit dans `.env.local` (gitignored) sous `VITE_EURIO_PAT`. Vite
 * l'injecte dans `import.meta.env` à la compilation. Pas de cookie ici :
 * studio-local est cross-origin (localhost → eurio-api.musubi.dev) et le
 * cookie SameSite=Lax ne traverse pas. Bearer header = solution propre.
 *
 * Pour l'auth cookie OIDC, voir `admin-vps` : c'est un autre frontend.
 * Spec : docs/work-in-progress/auth-redesign/ARCHITECTURE.md
 */

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
  if (!PAT) throw new MissingPatError()
  return { Authorization: `Bearer ${PAT}` }
}

export function hasPat(): boolean {
  return Boolean(PAT)
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = { ...authHeader() }
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
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
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, body),
  delete: <T>(path: string) => request<T>('DELETE', path),
}
