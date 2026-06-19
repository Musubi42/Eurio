/**
 * Wrapper fetch minimal autour de `eurio-api`.
 *
 * - `credentials: 'include'` pour envoyer le cookie `eurio_session` HttpOnly
 *   sur les requêtes cross-origin (panel @ eurio-admin.musubi.dev → API @
 *   eurio-api.musubi.dev).
 * - Erreur typée pour permettre au caller de distinguer 401/403/404/5xx.
 */

const API_BASE = import.meta.env.VITE_EURIO_API_BASE

export class ApiError extends Error {
  status: number
  body: unknown
  constructor(status: number, body: unknown, message: string) {
    super(message)
    this.status = status
    this.body = body
  }
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const init: RequestInit = {
    method,
    credentials: 'include',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  }
  const url = `${API_BASE}${path}`
  const res = await fetch(url, init)
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
    throw new ApiError(res.status, parsed, `${method} ${path}: ${res.status} ${detail}`)
  }
  return parsed as T
}

export const api = {
  base: API_BASE,
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body),
  delete: <T>(path: string) => request<T>('DELETE', path),
}
