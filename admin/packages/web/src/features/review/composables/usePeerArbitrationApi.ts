// Arbitrage admin des décisions des amis reviewers.
// Backed by ml/review/peer_arbitration_routes.py (/peer-arbitration).
// cf. docs/work-in-progress/collaborative-review/05-admin-arbitration.md

import { ML_API } from '@/features/training/composables/useTrainingApi'

export interface PeerDecision {
  id: string
  image_asset_id: string
  crop_url: string | null
  reviewer_name: string
  reviewer_token: string
  action: 'accept' | 'reject' | 'skip'
  decided_eurio_id: string | null
  decided_label: string | null
  decided_face: string | null
  quality_reason: string | null
  notes: string | null
  decided_at: string
  dino_top1_eurio_id: string | null
  dino_top1_label: string | null
  concords: boolean
}

export interface ReviewerStat {
  reviewer_name: string
  reviewer_token: string
  total: number
  approved: number
  rejected: number
  pending: number
}

/** Préfixe une URL crop relative (/sources/...) par l'origine du backend ML. */
export function cropSrc(url: string | null): string {
  return url ? `${ML_API}${url}` : ''
}

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${ML_API}${path}`, init)
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

export function usePeerArbitrationApi() {
  async function fetchPending(limit = 200): Promise<PeerDecision[]> {
    const data = await jsonFetch<{ items: PeerDecision[] }>(
      `/peer-arbitration?limit=${limit}`,
    )
    return data.items
  }

  async function fetchReviewerStats(): Promise<ReviewerStat[]> {
    const data = await jsonFetch<{ reviewers: ReviewerStat[] }>('/peer-arbitration/reviewers')
    return data.reviewers
  }

  async function approve(id: string): Promise<{ status: string }> {
    return jsonFetch(`/peer-arbitration/${id}/approve`, { method: 'POST' })
  }

  async function reject(id: string, notes?: string): Promise<{ status: string }> {
    return jsonFetch(`/peer-arbitration/${id}/reject`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ notes: notes ?? null }),
    })
  }

  return { fetchPending, fetchReviewerStats, approve, reject }
}
