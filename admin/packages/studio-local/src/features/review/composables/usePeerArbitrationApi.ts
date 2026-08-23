// Arbitrage des décisions des amis reviewers — la seconde moitié de la boucle
// de quarantaine (D7). Backed by `ml/review/peer_arbitration_routes.py`.
// cf. docs/work-in-progress/review-collaborative-v2/ROADMAP.md §lot 8

import { eurioApi } from '@/shared/api/eurio-api'

export interface PeerDecision {
  id: string
  image_asset_id: string
  /** Absolue (URL MinIO présignée) depuis le lot 8 — cf. `_crop_url` côté serveur. */
  crop_url: string | null
  /** Vignette canonique de la pièce DÉCIDÉE : l'arbitre compare crop ↔ cible. */
  canonical_url: string | null
  listing_title: string
  listing_url: string | null
  source: string
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
  /** `concords` | `disagrees` | `absent` — un silence de DINO n'est pas un désaccord. */
  dino_state: 'concords' | 'disagrees' | 'absent'
}

export interface PeerDecisionPage {
  items: PeerDecision[]
  total: number
  limit: number
  offset: number
}

export interface BatchResult {
  requested: number
  approved?: string[]
  rejected?: string[]
  superseded?: string[]
  failed: { id: string; detail: string; status: number }[]
}

export interface ReviewerStat {
  reviewer_name: string
  reviewer_token: string
  total: number
  approved: number
  rejected: number
  pending: number
}

/** Résout une URL de crop. Absolue depuis le lot 8 (MinIO présignée) : on la
 *  laisse passer. Le fallback relatif se résout contre eurio-api — JAMAIS contre
 *  `ML_API`, qui vaut `127.0.0.1:8042` et n'existe pas là où cette vue sert. */
export function cropSrc(url: string | null): string {
  if (!url) return ''
  return url.startsWith('http') ? url : `${eurioApi.base}${url}`
}

// Porté sur eurio-api (cookie OIDC en hébergé, Bearer PAT en local).
// `peer_arbitration_routes` est monté sur l'image lean (server_serve._CANDIDATES),
// ses écritures gardées par `review:arbitrate` (lot 4b).

export function usePeerArbitrationApi() {
  /** Une page de la file d'arbitrage. Le serveur trie : désaccords en tête (D8). */
  async function fetchPending(
    opts: { limit?: number; offset?: number; reviewer?: string | null } = {},
  ): Promise<PeerDecisionPage> {
    const qs = new URLSearchParams({
      limit: String(opts.limit ?? 60),
      offset: String(opts.offset ?? 0),
    })
    if (opts.reviewer) qs.set('reviewer', opts.reviewer)
    return eurioApi.get<PeerDecisionPage>(`/peer-arbitration?${qs.toString()}`)
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

  /** Approuve une sélection. Un item en échec ne fait pas tomber le lot. */
  async function approveBatch(ids: string[]): Promise<BatchResult> {
    return eurioApi.post<BatchResult>('/peer-arbitration/approve-batch', { ids })
  }

  /** Rejette une sélection — les crops RETOURNENT dans la file. */
  async function rejectBatch(ids: string[], notes?: string): Promise<BatchResult> {
    return eurioApi.post<BatchResult>('/peer-arbitration/reject-batch', {
      ids,
      notes: notes ?? null,
    })
  }

  return { fetchPending, fetchReviewerStats, approve, reject, approveBatch, rejectBatch }
}
