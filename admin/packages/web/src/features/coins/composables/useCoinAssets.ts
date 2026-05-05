// Coin enrichment assets — wraps ml/api/coin_assets_routes.py.
//
//   GET  /coins/{eurio_id}/assets?include_unresolved=&limit=&offset=
//   POST /coins/assets/reflag-needs-review
//
// Le `file_url` retourné est relatif (`/sources/<source>/assets/<id>/file`)
// — on le promeut en absolu via ML_API au moment du parse, comme
// `useDinoSuggestions` ou `useReviewApi`. Quand on basculera vers un
// backend S3 distant (cf. doc kickoff storage), le serveur renverra
// déjà des URLs absolues : la promotion sera no-op, pas de breaking.

import { ML_API } from '@/features/training/composables/useTrainingApi'

export type CoinAssetStatus =
  | 'auto_name'
  | 'auto_phash'
  | 'manual'
  | 'needs_review'
  | 'rejected'

export interface CoinAsset {
  id: string
  source: string
  source_ref: string
  listing_url: string | null
  listing_title: string | null
  file_url: string  // promoted to absolute URL client-side
  face: 'obverse' | 'reverse' | 'unknown' | null
  variant_kind: string
  resolution_status: CoinAssetStatus
  resolution_confidence: number | null
  decided_by: string | null
  resolved_at: string | null
  width: number | null
  height: number | null
}

export interface CoinAssetsPage {
  eurio_id: string
  total: number
  assets: CoinAsset[]
  next_offset: number | null
}

export interface ReflagResponse {
  n_reflagged: number
  n_skipped: number
  skipped_reasons: string[]
}

function promoteUrl(url: string): string {
  return url.startsWith('http') ? url : `${ML_API}${url}`
}

export async function fetchCoinAssets(
  eurioId: string,
  opts: { includeUnresolved?: boolean; limit?: number; offset?: number } = {},
): Promise<CoinAssetsPage> {
  const params = new URLSearchParams()
  if (opts.includeUnresolved) params.set('include_unresolved', 'true')
  params.set('limit', String(opts.limit ?? 60))
  params.set('offset', String(opts.offset ?? 0))
  const resp = await fetch(
    `${ML_API}/coins/${encodeURIComponent(eurioId)}/assets?${params.toString()}`,
  )
  if (!resp.ok) {
    throw new Error(`fetchCoinAssets failed: ${resp.status}`)
  }
  const body = (await resp.json()) as CoinAssetsPage
  return {
    ...body,
    assets: body.assets.map((a) => ({ ...a, file_url: promoteUrl(a.file_url) })),
  }
}

/** Compteur global eurio_id → n_enrichment, pour les badges sur la
 *  liste des coins. Une seule query côté ML — coût ~ms. */
export async function fetchEnrichmentCounts(): Promise<Record<string, number>> {
  const resp = await fetch(`${ML_API}/coins/enrichment-counts`)
  if (!resp.ok) return {}
  return (await resp.json()) as Record<string, number>
}

export async function reflagAssetsNeedsReview(
  assetIds: string[],
): Promise<ReflagResponse> {
  const resp = await fetch(`${ML_API}/coins/assets/reflag-needs-review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ asset_ids: assetIds }),
  })
  if (!resp.ok) {
    throw new Error(`reflagAssetsNeedsReview failed: ${resp.status}`)
  }
  return (await resp.json()) as ReflagResponse
}

// ─── Visual helpers ─────────────────────────────────────────────────────

export interface StatusVisual {
  ringColor: string
  label: string
  labelColor: string
}

/** Couleurs ring + label par statut. Les `auto_*` + `manual` n'ont pas
 *  de label (ce sont les "validés" — sobre, pas de bruit visuel). */
export function statusVisual(status: CoinAssetStatus): StatusVisual {
  switch (status) {
    case 'auto_name':
    case 'auto_phash':
      return {
        ringColor: 'var(--success)',
        label: '',
        labelColor: 'var(--success)',
      }
    case 'manual':
      return {
        ringColor: 'var(--indigo-700)',
        label: '',
        labelColor: 'var(--indigo-700)',
      }
    case 'needs_review':
      return {
        ringColor: 'var(--gold-600)',
        label: 'needs review',
        labelColor: 'var(--gold-600)',
      }
    case 'rejected':
      return {
        ringColor: 'var(--danger)',
        label: 'rejected',
        labelColor: 'var(--danger)',
      }
  }
}

/** Initiale source (e=ebay, n=numista, c=catawiki, …) — petite pastille. */
export function sourceInitial(source: string): string {
  return (source || '?').trim().charAt(0).toLowerCase() || '?'
}
