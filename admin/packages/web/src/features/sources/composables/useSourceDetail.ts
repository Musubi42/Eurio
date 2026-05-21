// Source detail composables — mocks for /sources/:id (V1).
//
// Le backend FastAPI sert déjà /sources/status (cf. ml/api/sources_routes.py)
// mais pas encore les sous-endpoints détail. Tant qu'ils n'existent pas, on
// mocke localement avec des signatures alignées sur ce qui sera servi
// (cf. docs/sources-refacto/admin-ux.md §"Endpoints attendus").

import { ML_API } from '@/features/training/composables/useTrainingApi'
import type { CliHint, HealthState, SourceId } from './useSourcesApi'
import { MOCK_SOURCES_STATUS } from './useSourcesApi'

// ─── Types ──────────────────────────────────────────────────────────────

export interface SourceDetailHeader {
  id: SourceId
  label: string
  subtitle: string
  health: HealthState
  health_reason: string | null
  expected_cadence_days: number
  last_run_at: string | null
  last_run_summary: {
    n_images: number
    n_quotes: number
    n_calls: number
    duration_s: number
    status: 'success' | 'partial' | 'failed'
  } | null
  coverage_pct: number
  coverage_label: string
}

export type RunKind = 'run' | 'dry' | 'backfill' | 'reset'
export type RunStatus = 'success' | 'partial' | 'failed' | 'running'

export interface SourceRun {
  id: string
  started_at: string
  kind: RunKind
  duration_s: number
  n_calls: number
  n_images: number
  n_quotes: number
  n_errors: number
  status: RunStatus
  filters: Record<string, unknown>
  log_path: string
}

export interface SourceImage {
  id: string
  thumb_url: string
  full_url: string
  eurio_id: string | null
  variant_kind: string | null
  quality_score: number | null
  training_eligible: boolean
  fetched_at: string
}

export interface SourceQuote {
  id: string
  eurio_id: string
  condition: 'UNC' | 'XF' | 'VF' | 'F' | 'unknown'
  p10: number
  p50: number
  p90: number
  n: number
  period: string
  fetched_at: string
}

export interface CoverageBreakdownEntry {
  key: string
  enriched: number
  total: number
  pct: number
}

export interface SourceCoverageDetail {
  global: { enriched: number; total: number; pct: number; unit: string }
  breakdown_dimension: string
  breakdown: CoverageBreakdownEntry[]
  uncovered_eurio_ids: string[]
}

// ─── Fetchers (real API, with mock fallback on network failure) ─────────
// Backed by ml/api/sources_routes.py. If the backend is unreachable we
// fall back to deterministic mocks so the page stays usable in pure-front
// dev (no FastAPI running).

async function getJson<T>(path: string): Promise<T | null> {
  try {
    const resp = await fetch(`${ML_API}${path}`)
    if (!resp.ok) {
      // 404 on detail = source not declared → caller throws below.
      // Other non-OK = treat as backend down → null = use mock.
      if (resp.status === 404) {
        const detail = await resp.json().catch(() => ({}))
        const msg = (detail && typeof detail === 'object' && 'detail' in detail)
          ? String((detail as { detail: unknown }).detail)
          : `HTTP 404`
        throw new Error(msg)
      }
      return null
    }
    return (await resp.json()) as T
  } catch (err) {
    // Network error (CORS, ECONNREFUSED, etc.) → mock fallback.
    if (err instanceof TypeError) return null
    throw err
  }
}

export async function fetchSourceDetail(id: SourceId): Promise<SourceDetailHeader> {
  const real = await getJson<SourceDetailHeader>(`/sources/${id}`)
  if (real) return real

  // Fallback (FastAPI down) — derived from MOCK_SOURCES_STATUS.
  const src = MOCK_SOURCES_STATUS.sources.find((s) => s.id === id)
  if (!src) {
    // Source unknown to the front mock too (e.g. `mock` — only declared
    // in the orchestrator registry). Return a benign synthetic header
    // so the page renders an empty-but-valid state instead of crashing.
    return {
      id,
      label: id,
      subtitle: 'Backend hors ligne — pas de métadonnées disponibles',
      health: 'warning',
      health_reason: 'API indisponible',
      expected_cadence_days: 0,
      last_run_at: null,
      last_run_summary: null,
      coverage_pct: 0,
      coverage_label: '—',
    }
  }
  const lastRun: SourceDetailHeader['last_run_summary'] = src.is_future
    ? null
    : {
        n_images: pseudoCount(id, 'images', 47),
        n_quotes: id === 'ebay' ? pseudoCount(id, 'quotes', 23) : 0,
        n_calls: pseudoCount(id, 'calls', 487),
        duration_s: pseudoCount(id, 'dur', 872),
        status: src.health === 'error' ? 'failed' : 'success',
      }
  return {
    id: src.id,
    label: src.label,
    subtitle: src.subtitle,
    health: src.health,
    health_reason: src.health_reason,
    expected_cadence_days: src.temporal.expected_cadence_days,
    last_run_at: src.temporal.last_run_at,
    last_run_summary: lastRun,
    coverage_pct: src.coverage.pct,
    coverage_label: `${src.coverage.enriched.toLocaleString('fr-FR')} / ${src.coverage.total_target.toLocaleString('fr-FR')} ${src.coverage.unit}`,
  }
}

export async function fetchSourceRuns(
  id: SourceId,
  opts: { limit?: number; status?: RunStatus } = {},
): Promise<SourceRun[]> {
  const params = new URLSearchParams()
  if (opts.limit) params.set('limit', String(opts.limit))
  if (opts.status) params.set('status', opts.status)
  const qs = params.size ? `?${params.toString()}` : ''
  const real = await getJson<SourceRun[]>(`/sources/${id}/runs${qs}`)
  if (real) return real

  await delay(120)
  const limit = opts.limit ?? 50
  const all = generateMockRuns(id, limit + 5)
  return opts.status ? all.filter((r) => r.status === opts.status).slice(0, limit) : all.slice(0, limit)
}

export async function fetchSourceImages(
  id: SourceId,
  opts: { page?: number; pageSize?: number } = {},
): Promise<{ items: SourceImage[]; total: number }> {
  const params = new URLSearchParams()
  if (opts.page) params.set('page', String(opts.page))
  if (opts.pageSize) params.set('pageSize', String(opts.pageSize))
  const qs = params.size ? `?${params.toString()}` : ''
  const real = await getJson<{ items: SourceImage[]; total: number }>(
    `/sources/${id}/images${qs}`,
  )
  if (real) {
    // Backend returns relative URLs (/sources/:id/assets/:asset_id/file).
    // Prepend ML_API so <img> tags can load them cross-origin.
    return {
      ...real,
      items: real.items.map((it) => ({
        ...it,
        thumb_url: it.thumb_url.startsWith('http') ? it.thumb_url : `${ML_API}${it.thumb_url}`,
        full_url: it.full_url.startsWith('http') ? it.full_url : `${ML_API}${it.full_url}`,
      })),
    }
  }

  await delay(120)
  const pageSize = opts.pageSize ?? 24
  const all = generateMockImages(id, 240)
  const start = ((opts.page ?? 1) - 1) * pageSize
  return { items: all.slice(start, start + pageSize), total: all.length }
}

export async function fetchSourceQuotes(
  id: SourceId,
  opts: { page?: number; pageSize?: number } = {},
): Promise<{ items: SourceQuote[]; total: number }> {
  const params = new URLSearchParams()
  if (opts.page) params.set('page', String(opts.page))
  if (opts.pageSize) params.set('pageSize', String(opts.pageSize))
  const qs = params.size ? `?${params.toString()}` : ''
  const real = await getJson<{ items: SourceQuote[]; total: number }>(
    `/sources/${id}/quotes${qs}`,
  )
  if (real) return real

  await delay(120)
  if (id !== 'ebay') return { items: [], total: 0 }
  const pageSize = opts.pageSize ?? 25
  const all = generateMockQuotes(120)
  const start = ((opts.page ?? 1) - 1) * pageSize
  return { items: all.slice(start, start + pageSize), total: all.length }
}

export async function fetchSourceCoverage(id: SourceId): Promise<SourceCoverageDetail> {
  const real = await getJson<SourceCoverageDetail>(`/sources/${id}/coverage`)
  if (real) {
    // Real response, even if breakdown is empty (V1 — joins land later).
    // For sources known to the front mock registry, augment the empty
    // breakdown with mock data so the widget isn't blank in dev.
    if (real.breakdown.length === 0 && MOCK_SOURCES_STATUS.sources.some((s) => s.id === id)) {
      return {
        ...real,
        breakdown_dimension: breakdownDimensionFor(id),
        breakdown: generateMockBreakdown(id),
        uncovered_eurio_ids: generateUncoveredIds(id, 24),
      }
    }
    return real
  }

  // Pure mock fallback (FastAPI down) — only works for sources known to
  // the front mock registry. For other ids (e.g. `mock`), surface a
  // benign empty payload so the page stays usable.
  await delay(100)
  const src = MOCK_SOURCES_STATUS.sources.find((s) => s.id === id)
  if (!src) {
    return {
      global: { enriched: 0, total: 0, pct: 0, unit: 'items' },
      breakdown_dimension: '—',
      breakdown: [],
      uncovered_eurio_ids: [],
    }
  }
  return {
    global: {
      enriched: src.coverage.enriched,
      total: src.coverage.total_target,
      pct: src.coverage.pct,
      unit: src.coverage.unit,
    },
    breakdown_dimension: breakdownDimensionFor(id),
    breakdown: generateMockBreakdown(id),
    uncovered_eurio_ids: generateUncoveredIds(id, 24),
  }
}

export function fetchSourceCommands(id: SourceId): CliHint[] {
  const src = MOCK_SOURCES_STATUS.sources.find((s) => s.id === id)
  return src?.cli_hints ?? []
}

// ─── Trigger + poll (real API) ──────────────────────────────────────────
// Backed by `ml/api/sources_routes.py` :
//   POST /sources/:id/runs?dry_run=...&force=...
//   GET  /sources/:id/runs/:run_id
// Sources without an adapter return 501 — caller can surface the message.

export interface RunSnapshot {
  id: string
  source: string
  kind: 'run' | 'dry'
  status: RunStatus
  current_step: string | null
  started_at: string
  ended_at: string | null
  duration_s: number | null
  n_calls: number
  n_raws_added: number
  n_crops_added: number
  n_quotes_added: number
  n_pending_added: number
  n_auto_resolved: number
  n_review_enqueued: number
  n_errors: number
  filters: Record<string, unknown>
  error_summary: string | null
  log_path: string | null
}

export interface DiscoveryGroupSpec {
  denomination: number
  country: string
  year: number
}

export interface TriggerRunOptions {
  dryRun?: boolean
  force?: boolean
  filters?: {
    country?: string
    denomination?: string
    year?: number
    target_eurio_id?: string
    target_eurio_ids?: string[]
    discovery_groups?: DiscoveryGroupSpec[]
    limit?: number
    extra?: Record<string, unknown>
  }
}

// ─── eBay-specific endpoints (phase 3.C) ──────────────────────────────────

export interface EbayQuotaStatus {
  calls_today: number
  limit: number
  remaining: number
  exhausted: boolean
  period: string
  avg_calls_per_eurio_id: number
}

/**
 * Freshness queue à la maille GROUPE de découverte (denom, pays, année).
 * Une recherche eBay couvre tout un groupe — c'est l'unité de run.
 */
export interface EbayFreshnessGroupItem {
  denomination: number
  country: string
  year: number
  n_coins: number
  last_enriched_at: string | null
  n_images: number
  n_crops: number
  status: 'never' | 'stale' | 'fresh'
}

export interface EbayFreshnessGroupsResponse {
  items: EbayFreshnessGroupItem[]
  buckets: { never: number; stale_90d: number; fresh: number; total: number }
}

export async function fetchEbayQuotaStatus(): Promise<EbayQuotaStatus | null> {
  try {
    const resp = await fetch(`${ML_API}/sources/ebay/quota-status`)
    if (!resp.ok) return null
    return await resp.json()
  } catch { return null }
}

export async function fetchEbayFreshnessGroups(
  limit = 200,
): Promise<EbayFreshnessGroupsResponse | null> {
  try {
    const resp = await fetch(`${ML_API}/sources/ebay/freshness-groups?limit=${limit}`)
    if (!resp.ok) return null
    return await resp.json()
  } catch { return null }
}

export class TriggerError extends Error {
  constructor(public readonly status: number, message: string, public readonly detail?: unknown) {
    super(message)
  }
}

export async function triggerSourceRun(
  id: SourceId,
  opts: TriggerRunOptions = {},
): Promise<{ run_id: string; status: 'started'; kind: 'run' | 'dry' }> {
  const params = new URLSearchParams()
  if (opts.dryRun) params.set('dry_run', 'true')
  if (opts.force) params.set('force', 'true')
  const url = `${ML_API}/sources/${id}/runs${params.size ? '?' + params.toString() : ''}`
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(opts.filters ?? {}),
  })
  if (!resp.ok) {
    let detail: unknown = null
    try { detail = await resp.json() } catch { /* ignore */ }
    const msg = typeof detail === 'object' && detail && 'detail' in detail
      ? typeof (detail as { detail: unknown }).detail === 'string'
        ? (detail as { detail: string }).detail
        : JSON.stringify((detail as { detail: unknown }).detail)
      : `HTTP ${resp.status}`
    throw new TriggerError(resp.status, msg, detail)
  }
  return resp.json()
}

export async function fetchSourceRun(id: SourceId, runId: string): Promise<RunSnapshot> {
  const resp = await fetch(`${ML_API}/sources/${id}/runs/${runId}`)
  if (!resp.ok) throw new TriggerError(resp.status, `HTTP ${resp.status}`)
  return resp.json()
}

/**
 * Poll a run until it leaves `status='running'`. Calls `onTick` after every
 * snapshot so the UI can show step / counters live. Aborts on 404/500 or
 * after `maxIntervals`.
 */
export async function pollSourceRun(
  id: SourceId,
  runId: string,
  opts: {
    intervalMs?: number
    maxIntervals?: number
    onTick?: (snap: RunSnapshot) => void
    signal?: AbortSignal
  } = {},
): Promise<RunSnapshot> {
  const interval = opts.intervalMs ?? 2000
  const max = opts.maxIntervals ?? 600  // 20min @ 2s — generous for real sources
  for (let i = 0; i < max; i++) {
    if (opts.signal?.aborted) throw new TriggerError(0, 'aborted')
    const snap = await fetchSourceRun(id, runId)
    opts.onTick?.(snap)
    if (snap.status !== 'running') return snap
    await delay(interval)
  }
  throw new TriggerError(0, `Polling timed out after ${max} ticks`)
}

// ─── Mock generators ────────────────────────────────────────────────────

function delay(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

function pseudoCount(seed: string, salt: string, base: number): number {
  let h = 0
  for (const c of seed + salt) h = (h * 31 + c.charCodeAt(0)) | 0
  return Math.abs(h % base) + Math.floor(base * 0.4)
}

function generateMockRuns(id: SourceId, n: number): SourceRun[] {
  const now = Date.parse('2026-04-26T14:32:11Z')
  const oneDay = 24 * 3600 * 1000
  const runs: SourceRun[] = []
  for (let i = 0; i < n; i++) {
    const offsetDays = i === 0 ? 0 : i * 2 + (i % 3)
    const started = new Date(now - offsetDays * oneDay - (i % 5) * 3600 * 1000)
    const isDry = i % 7 === 3
    const isFailed = i === 4 && id !== 'wikipedia'
    runs.push({
      id: `${id}-run-${i}`,
      started_at: started.toISOString(),
      kind: isDry ? 'dry' : 'run',
      duration_s: isDry ? 2 : pseudoCount(id, `dur-${i}`, 600) + 120,
      n_calls: isDry ? 0 : pseudoCount(id, `calls-${i}`, 500) + 50,
      n_images: isDry ? 0 : pseudoCount(id, `img-${i}`, 60),
      n_quotes: isDry || id !== 'ebay' ? 0 : pseudoCount(id, `q-${i}`, 30),
      n_errors: isFailed ? 12 : i % 9 === 0 ? 1 : 0,
      status: isFailed ? 'failed' : 'success',
      filters: isDry ? { limit: 5 } : i % 6 === 2 ? { countries: ['FR', 'DE'] } : {},
      log_path: `ml/state/logs/${id}/run-${i}.log`,
    })
  }
  return runs
}

function generateMockImages(id: SourceId, n: number): SourceImage[] {
  const imgs: SourceImage[] = []
  for (let i = 0; i < n; i++) {
    const eurioId = i % 11 === 7 ? null : `${pickCountry(i)}-2eur-${1999 + (i % 27)}-comm`
    imgs.push({
      id: `${id}-img-${i}`,
      thumb_url: `https://placehold.co/120x120/EDEDF5/1A1B4B?text=${id.slice(0, 3)}-${i}`,
      full_url: `https://placehold.co/600x600/EDEDF5/1A1B4B?text=${id}-${i}`,
      eurio_id: eurioId,
      variant_kind: i % 4 === 0 ? 'commemorative' : i % 4 === 1 ? 'standard' : null,
      quality_score: 0.4 + (pseudoCount(id, `q-${i}`, 60) / 100),
      training_eligible: i % 5 !== 2,
      fetched_at: new Date(Date.parse('2026-04-26T00:00:00Z') - i * 1800 * 1000).toISOString(),
    })
  }
  return imgs
}

function generateMockQuotes(n: number): SourceQuote[] {
  const quotes: SourceQuote[] = []
  const conditions: SourceQuote['condition'][] = ['UNC', 'XF', 'VF', 'F', 'unknown']
  for (let i = 0; i < n; i++) {
    const country = pickCountry(i)
    const year = 2002 + (i % 24)
    const p50 = 4 + pseudoCount('q', `p-${i}`, 18)
    quotes.push({
      id: `q-${i}`,
      eurio_id: `${country}-${year}-2eur-comm`,
      condition: conditions[i % conditions.length],
      p10: Math.round(p50 * 0.6 * 100) / 100,
      p50,
      p90: Math.round(p50 * 1.7 * 100) / 100,
      n: 8 + (i % 22),
      period: '2026-04',
      fetched_at: new Date(Date.parse('2026-04-26T00:00:00Z') - i * 7200 * 1000).toISOString(),
    })
  }
  return quotes
}

function pickCountry(seed: number): string {
  const codes = ['be', 'fr', 'de', 'it', 'es', 'nl', 'lu', 'ie', 'pt', 'fi', 'gr', 'at', 'cy', 'mt', 'sk', 'si', 'ee', 'lv', 'lt', 'hr', 'bg']
  return codes[seed % codes.length]
}

function breakdownDimensionFor(id: SourceId): string {
  if (id === 'ebay') return 'pays'
  if (id === 'numista_match' || id === 'numista_enrich' || id === 'numista_images') return 'pays'
  if (id === 'mdp' || id === 'lmdlp') return 'condition'
  if (id === 'bce') return 'année'
  if (id === 'wikipedia') return 'pays'
  return 'catégorie'
}

function generateMockBreakdown(id: SourceId): CoverageBreakdownEntry[] {
  const dim = breakdownDimensionFor(id)
  if (dim === 'pays') {
    const codes = ['BE', 'FR', 'DE', 'IT', 'ES', 'NL', 'LU', 'IE', 'PT', 'FI', 'GR', 'AT', 'CY', 'MT', 'SK', 'SI', 'EE', 'LV', 'LT', 'HR', 'BG']
    return codes.map((c, i) => {
      const total = 18 + (i % 6) * 4
      const enriched = Math.max(0, total - pseudoCount(id, `c-${c}`, 14))
      return { key: c, enriched, total, pct: total ? (100 * enriched) / total : 0 }
    })
  }
  if (dim === 'année') {
    const years = Array.from({ length: 23 }, (_, i) => 2002 + i)
    return years.map((y, i) => {
      const total = 8
      const enriched = Math.max(0, total - (i % 3 === 0 ? 1 : 0))
      return { key: String(y), enriched, total, pct: (100 * enriched) / total }
    })
  }
  return ['UNC', 'XF', 'VF', 'F', 'unknown'].map((c, i) => {
    const total = 100 + i * 30
    const enriched = total - pseudoCount(id, `cat-${c}`, 40)
    return { key: c, enriched, total, pct: (100 * enriched) / total }
  })
}

function generateUncoveredIds(_id: SourceId, n: number): string[] {
  const out: string[] = []
  for (let i = 0; i < n; i++) {
    out.push(`${pickCountry(i + 3)}-2eur-${2010 + (i % 16)}-comm-${(i % 4) + 1}`)
  }
  return out
}
