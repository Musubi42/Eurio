// Arbitrage admin des décisions des amis reviewers.
// Backed by ml/review/peer_arbitration_routes.py (/peer-arbitration).
// cf. docs/work-in-progress/collaborative-review/05-admin-arbitration.md

import { eurioApi } from '@/shared/api/eurio-api'
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

// Phase 3 : porté sur eurio-api (Bearer PAT). peer_arbitration_routes monté
// en best-effort sur l'image lean (cf. server_serve._CANDIDATES).

export function usePeerArbitrationApi() {
  async function fetchPending(limit = 200): Promise<PeerDecision[]> {
    const data = await eurioApi.get<{ items: PeerDecision[] }>(
      `/peer-arbitration?limit=${limit}`,
    )
    return data.items
  }

  async function fetchReviewerStats(): Promise<ReviewerStat[]> {
    const data = await eurioApi.get<{ reviewers: ReviewerStat[] }>('/peer-arbitration/reviewers')
    return data.reviewers
  }

  async function approve(id: string): Promise<{ status: string }> {
    return eurioApi.post<{ status: string }>(`/peer-arbitration/${id}/approve`)
  }

  async function reject(id: string, notes?: string): Promise<{ status: string }> {
    return eurioApi.post<{ status: string }>(
      `/peer-arbitration/${id}/reject`,
      { notes: notes ?? null },
    )
  }

  return { fetchPending, fetchReviewerStats, approve, reject }
}
