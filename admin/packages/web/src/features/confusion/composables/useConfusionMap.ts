import { supabase } from '@/shared/supabase/client'
import type {
  Coin,
  ConfusionNeighbor,
  ConfusionZone,
} from '@/shared/supabase/types'
import { firstImageUrl } from '@/shared/utils/coin-images'
import { zoneFromSimilarity } from './useConfusionZone'

export const ML_API = 'http://localhost:8042'
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
  const { data, error } = await supabase
    .from('coin_confusion_map')
    .select('zone, nearest_similarity, computed_at, encoder_version')
    .eq('encoder_version', ENCODER_VERSION)

  if (error) throw error
  const rows = (data ?? []) as Array<{
    zone: ConfusionZone
    nearest_similarity: number
    computed_at: string
    encoder_version: string
  }>

  const by_zone: Record<ConfusionZone, number> = { green: 0, orange: 0, red: 0 }
  const bins: HistogramBin[] = Array.from({ length: 20 }, (_, i) => ({
    bin_start: Math.round(i * 0.05 * 100) / 100,
    count: 0,
  }))
  let last: string | null = null

  for (const r of rows) {
    by_zone[r.zone] = (by_zone[r.zone] ?? 0) + 1
    const idx = Math.min(19, Math.max(0, Math.floor(r.nearest_similarity * 20)))
    bins[idx].count += 1
    if (!last || r.computed_at > last) last = r.computed_at
  }

  return {
    total: rows.length,
    by_zone,
    last_computed_at: last,
    encoder_version: ENCODER_VERSION,
    histogram_bins: bins,
  }
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
  // Strategy:
  //   1. If personal !== 'all' — first resolve the candidate eurio_id set on
  //      `coins.personal_owned = true`. With ~78 owned coins this is a single
  //      cheap query and keeps the filter strictly server-side.
  //   2. Then query confusion_map with the appropriate `eurio_id in (...)` /
  //      neighbor constraint. PostgREST can't join across tables in a single
  //      filter, so we bring the set client-side and feed it back as `in`.
  let ownedIds: Set<string> | null = null
  if (opts.personal !== 'all') {
    const { data, error } = await supabase
      .from('coins')
      .select('eurio_id')
      .eq('personal_owned', true)
    if (error) throw error
    ownedIds = new Set((data ?? []).map(r => (r as { eurio_id: string }).eurio_id))
    // Empty set → no possible match, short-circuit.
    if (ownedIds.size === 0) return []
  }

  let q = supabase
    .from('coin_confusion_map')
    .select('eurio_id, nearest_eurio_id, nearest_similarity, zone')
    .eq('encoder_version', ENCODER_VERSION)
    .not('nearest_eurio_id', 'is', null)
    .order('nearest_similarity', { ascending: false })

  if (opts.zone !== 'all') q = q.eq('zone', opts.zone)

  if (ownedIds !== null) {
    const owned = [...ownedIds]
    if (opts.personal === 'both') {
      // Both endpoints owned → row.eurio_id ∈ owned AND nearest ∈ owned.
      q = q.in('eurio_id', owned).in('nearest_eurio_id', owned)
    }
    else {
      // 'either' → at least one endpoint owned. PostgREST OR clause:
      //   eurio_id in (...) OR nearest_eurio_id in (...)
      const list = owned.map(id => `"${id}"`).join(',')
      q = q.or(`eurio_id.in.(${list}),nearest_eurio_id.in.(${list})`)
    }
  }

  // Always apply a generous over-fetch ceiling so we have material to dedupe
  // pairs (A↔B and B↔A both surface in confusion_map). 4× should cover.
  q = q.limit(opts.limit * 4)

  const { data, error } = await q
  if (error) throw error

  const rawRows = (data ?? []) as Array<{
    eurio_id: string
    nearest_eurio_id: string
    nearest_similarity: number
    zone: ConfusionZone
  }>

  // Dedupe symmetric pairs and cap to opts.limit (mirrors the ML API path).
  const seen = new Set<string>()
  const rows: typeof rawRows = []
  for (const r of rawRows) {
    const key = r.eurio_id < r.nearest_eurio_id
      ? `${r.eurio_id}__${r.nearest_eurio_id}`
      : `${r.nearest_eurio_id}__${r.eurio_id}`
    if (seen.has(key)) continue
    seen.add(key)
    rows.push(r)
    if (rows.length >= opts.limit) break
  }

  // Collect unique eurio_ids to enrich in a single IN() query
  const ids = new Set<string>()
  for (const r of rows) {
    ids.add(r.eurio_id)
    ids.add(r.nearest_eurio_id)
  }
  const coinMap = await fetchCoinRefs([...ids])

  return rows.map(r => ({
    eurio_id_a: r.eurio_id,
    eurio_id_b: r.nearest_eurio_id,
    similarity: r.nearest_similarity,
    zone: r.zone,
    coin_a: coinMap.get(r.eurio_id) ?? fallbackRef(r.eurio_id),
    coin_b: coinMap.get(r.nearest_eurio_id) ?? fallbackRef(r.nearest_eurio_id),
  }))
}

function fallbackRef(id: string): PairCoinRef {
  return { eurio_id: id, country: '—', year: null, theme: null, face_value: 0, image_url: null }
}

async function fetchCoinRefs(ids: string[]): Promise<Map<string, PairCoinRef>> {
  const out = new Map<string, PairCoinRef>()
  if (ids.length === 0) return out
  // Chunk to stay under URL-length limits
  const chunkSize = 200
  for (let i = 0; i < ids.length; i += chunkSize) {
    const chunk = ids.slice(i, i + chunkSize)
    const { data, error } = await supabase
      .from('coins')
      .select('eurio_id, country, year, theme, face_value, images, issue_type')
      .in('eurio_id', chunk)
    if (error) throw error
    for (const raw of (data ?? [])) {
      const c = raw as unknown as Coin & { issue_type: string | null }
      out.set(c.eurio_id, {
        eurio_id: c.eurio_id,
        country: c.country,
        year: c.year,
        theme: c.theme,
        face_value: c.face_value,
        image_url: firstImageUrl(c),
        issue_type: c.issue_type,
      })
    }
  }
  return out
}

/* ───────── Detail per-coin (ML API + Supabase fallback) ───────── */

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
  const { data, error } = await supabase
    .from('coin_confusion_map')
    .select('zone, nearest_similarity, nearest_eurio_id, top_k_neighbors')
    .eq('encoder_version', ENCODER_VERSION)
    .eq('eurio_id', eurioId)
    .maybeSingle()

  if (error) throw error
  if (!data) return null

  const neighbors = (data.top_k_neighbors ?? []) as unknown as ConfusionNeighbor[]
  const ids = neighbors.map(n => n.eurio_id)
  const refs = await fetchCoinRefs(ids)

  return {
    zone: data.zone as ConfusionZone,
    nearest_similarity: data.nearest_similarity,
    nearest_eurio_id: data.nearest_eurio_id,
    top_k_neighbors: neighbors.map(n => ({
      eurio_id: n.eurio_id,
      similarity: n.similarity,
      coin: refs.get(n.eurio_id) ?? null,
    })),
  }
}

/* ───────── Zones map (for CoinsPage badges) ───────── */

export async function fetchZoneMap(): Promise<
  Map<string, { zone: ConfusionZone, nearest_similarity: number }>
> {
  const out = new Map<string, { zone: ConfusionZone, nearest_similarity: number }>()
  const { data, error } = await supabase
    .from('coin_confusion_map')
    .select('eurio_id, zone, nearest_similarity')
    .eq('encoder_version', ENCODER_VERSION)
  if (error) throw error
  for (const r of (data ?? []) as Array<{
    eurio_id: string, zone: ConfusionZone, nearest_similarity: number
  }>) {
    out.set(r.eurio_id, { zone: r.zone, nearest_similarity: r.nearest_similarity })
  }
  return out
}

/* ───────── Utils ───────── */

export { zoneFromSimilarity }
