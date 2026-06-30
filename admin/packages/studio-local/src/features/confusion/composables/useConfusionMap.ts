import { eurioApi } from '@/shared/api/eurio-api'
import { ML_API } from '@/shared/api/ml-api'
import { HAS_LOCAL_ML_API } from '@/shared/config/deploy-target'
import type { ConfusionZone } from '@/shared/supabase/types'
import { zoneFromSimilarity } from './useConfusionZone'

// Re-export so existing importers of this module don't need to change.
export { ML_API }
export const ENCODER_VERSION = 'dinov2-vits14'

/* ───────── Types ───────── */

export interface ComputeStatus {
  running: boolean
  error: string | null
  job_id: string | null
  progress: { current: number, total: number, stage: string }
  last_computed_at: string | null
}

export interface HistogramBin {
  bin_start: number
  count: number
}

export interface ConfusionStats {
  total: number
  by_zone: Record<ConfusionZone, number>
  last_computed_at: string | null
  encoder_version: string
  histogram_bins: HistogramBin[]
}

export interface PairCoinRef {
  eurio_id: string
  country: string
  year: number | null
  theme: string | null
  face_value: number
  image_url: string | null
  issue_type?: string | null
}

export interface ConfusionPair {
  eurio_id_a: string
  eurio_id_b: string
  similarity: number
  zone: ConfusionZone
  coin_a: PairCoinRef
  coin_b: PairCoinRef
}

export interface CoinConfusionDetail {
  zone: ConfusionZone
  nearest_similarity: number
  nearest_eurio_id: string | null
  top_k_neighbors: Array<{
    eurio_id: string
    similarity: number
    coin: PairCoinRef | null
  }>
}

/* ───────── ML API availability ───────── */

export async function checkMlApiOnline(): Promise<boolean> {
  if (!HAS_LOCAL_ML_API) return false
  try {
    const resp = await fetch(`${ML_API}/health`, {
      signal: AbortSignal.timeout(3000),
    })
    return resp.ok
  } catch {
    return false
  }
}

/* ───────── Compute ───────── */

export async function postCompute(body: {
  eurio_ids?: string[]
  limit?: number
  encoder_version?: string
} = {}): Promise<{ started: boolean, job_id: string | null }> {
  const resp = await fetch(`${ML_API}/confusion-map/compute`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!resp.ok) throw new Error(`compute failed: ${resp.status}`)
  return resp.json()
}

export async function fetchStatus(): Promise<ComputeStatus> {
  const resp = await fetch(`${ML_API}/confusion-map/status`, {
    signal: AbortSignal.timeout(3000),
  })
  if (!resp.ok) throw new Error(`status failed: ${resp.status}`)
  return resp.json()
}

/* ───────── Stats (ML API + Supabase fallback) ───────── */

export async function fetchStats(preferMlApi: boolean): Promise<ConfusionStats> {
  if (preferMlApi) {
    try {
      const resp = await fetch(`${ML_API}/confusion-map/stats`, {
        signal: AbortSignal.timeout(5000),
      })
      if (resp.ok) return await resp.json()
    } catch {
      /* fallthrough to supabase */
    }
  }
  return fetchStatsFromSupabase()
}

async function fetchStatsFromSupabase(): Promise<ConfusionStats> {
  // Phase 1 data-layer-unification : eurio-api lit la même table SQLite que
  // l'API ML_API local. Le nom "FromSupabase" est conservé pour minimiser
  // le diff — sera renommé en Phase 4 quand on dropera Supabase.
  return eurioApi.get<ConfusionStats>(
    `/confusion-map/stats?encoder_version=${encodeURIComponent(ENCODER_VERSION)}`,
  )
}

/* ───────── Pairs (ML API + Supabase fallback) ───────── */

/**
 * Personal-collection filter mode for pairs.
 *
 * - `all`     : no filter
 * - `both`    : strict — both coin_a AND coin_b are personal_owned
 * - `either`  : partial — at least one of A or B is personal_owned
 *
 * Filtering happens at query time on Supabase (and fetch-time post-filter on
 * the ML API path) — never client-side over a paginated set, since the data
 * volume is large and we'd silently drop pairs.
 */
export type PersonalFilter = 'all' | 'both' | 'either'

export interface FetchPairsOpts {
  limit?: number
  zone?: 'all' | ConfusionZone
  personal?: PersonalFilter
}

export async function fetchPairs(
  preferMlApi: boolean,
  opts: FetchPairsOpts = {},
): Promise<ConfusionPair[]> {
  const { limit = 100, zone = 'all', personal = 'all' } = opts
  // The ML API doesn't yet expose a personal_owned filter, so when the user
  // selects one we go straight to Supabase where we can join cleanly.
  if (preferMlApi && personal === 'all') {
    try {
      const url = new URL(`${ML_API}/confusion-map/pairs`)
      url.searchParams.set('limit', String(limit))
      if (zone !== 'all') url.searchParams.set('zone', zone)
      const resp = await fetch(url.toString(), {
        signal: AbortSignal.timeout(8000),
      })
      if (resp.ok) return await resp.json()
    } catch {
      /* fallthrough */
    }
  }
  return fetchPairsFromSupabase({ limit, zone, personal })
}

async function fetchPairsFromSupabase(
  opts: { limit: number, zone: 'all' | ConfusionZone, personal: PersonalFilter },
): Promise<ConfusionPair[]> {
  // Phase 1 data-layer-unification : eurio-api fait tout le boulot
  // (jointure coins + dédup + enrichissement image). Plus de query
  // multi-step côté front.
  const params = new URLSearchParams({
    encoder_version: ENCODER_VERSION,
    limit: String(opts.limit),
    zone: opts.zone,
    personal: opts.personal,
  })
  return eurioApi.get<ConfusionPair[]>(`/confusion-map/pairs?${params.toString()}`)
}

/* ───────── Detail per-coin (ML API + eurio-api fallback) ───────── */

export async function fetchCoinDetail(
  eurioId: string,
  preferMlApi: boolean,
): Promise<CoinConfusionDetail | null> {
  if (preferMlApi) {
    try {
      const resp = await fetch(
        `${ML_API}/confusion-map/coin/${encodeURIComponent(eurioId)}`,
        { signal: AbortSignal.timeout(5000) },
      )
      if (resp.ok) return await resp.json()
      if (resp.status === 404) return null
    } catch {
      /* fallthrough */
    }
  }
  return fetchCoinDetailFromSupabase(eurioId)
}

async function fetchCoinDetailFromSupabase(
  eurioId: string,
): Promise<CoinConfusionDetail | null> {
  // Phase 1 data-layer-unification : eurio-api intègre l'enrichissement
  // top_k_neighbors avec les coin refs en une seule requête.
  return eurioApi.get<CoinConfusionDetail | null>(
    `/confusion-map/coin/${encodeURIComponent(eurioId)}`
    + `?encoder_version=${encodeURIComponent(ENCODER_VERSION)}`,
  )
}

/* ───────── Zones map (for CoinsPage badges) ───────── */

export async function fetchZoneMap(): Promise<
  Map<string, { zone: ConfusionZone, nearest_similarity: number }>
> {
  const data = await eurioApi.get<
    Record<string, { zone: ConfusionZone, nearest_similarity: number }>
  >(`/confusion-map/zone-map?encoder_version=${encodeURIComponent(ENCODER_VERSION)}`)
  return new Map(Object.entries(data))
}

/* ───────── Utils ───────── */

export { zoneFromSimilarity }
