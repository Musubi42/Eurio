// Client du service review. credentials:'include' → cookie de session.

const API = import.meta.env.VITE_REVIEW_API || 'http://localhost:8048'

export interface Candidate {
  eurio_id: string
  score: number
  label: string
  country: string
  denomination: string
  year: number | null
  thumb_url: string
}

export interface ReviewItem {
  id: string
  image_asset_id: string
  crop_url: string
  source: string | null
  listing_title: string | null
  candidates: Candidate[]
  target_eurio_id: string | null
  dino_top1: Candidate | null
}

export class AuthError extends Error {}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${API}${path}`, { credentials: 'include', ...init })
  if (resp.status === 401) throw new AuthError('Non authentifié')
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({ detail: `HTTP ${resp.status}` }))
    throw new Error(
      typeof detail === 'object' && detail && 'detail' in detail
        ? String((detail as { detail: unknown }).detail)
        : `HTTP ${resp.status}`,
    )
  }
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
  auth: (token: string) => postJson<{ name: string; token: string }>('/auth', { token }),
  me: () => req<{ name: string; token: string }>('/me'),
  claim: () => postJson<{ items: ReviewItem[]; window: number }>('/claim', {}),
  myItems: () => req<{ items: ReviewItem[]; window: number }>('/me/items'),
  decide: (
    id: string,
    payload: { action: 'accept' | 'reject'; eurio_id?: string; face?: string; quality_reason?: string },
  ) => postJson<{ status: string }>(`/items/${id}/decide`, payload),
  skip: (id: string) => postJson<{ status: string }>(`/items/${id}/skip`, {}),
  stats: () => req<{ total: number; today: number; name: string }>('/me/stats'),
}
