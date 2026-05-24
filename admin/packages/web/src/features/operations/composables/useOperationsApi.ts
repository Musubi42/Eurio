// Operations dashboard API — thin fetch wrappers around ML FastAPI.
// Backend: ml/api/operations_routes.py — endpoints under /operations/*.

import { ML_API } from '@/features/training/composables/useTrainingApi'

// ─── Section 1 — Pulse ─────────────────────────────────────────────────

export interface PulseDay {
  day: string
  marketplace: string
  searches: number
  raw: number
  kept: number
}

export interface PulseMarketplaceTotal {
  marketplace: string
  searches: number
  raw: number
  kept: number
  recall_pct: number
}

export interface PulseLastRun {
  run_id: string | null
  started_at: string | null
  ended_at: string | null
  status: string | null
}

export interface PulseResponse {
  window_days: number
  days: PulseDay[]
  by_marketplace: PulseMarketplaceTotal[]
  last_run: PulseLastRun
}

// ─── Section 2 — Training readiness ────────────────────────────────────

export type Tier = 'red' | 'warn' | 'green'

export interface ClassReadiness {
  class_id: string
  eurio_ids: string[]
  label: string | null
  country: string | null
  year: number | null
  n_canon: number
  n_wild: number
  n_total: number
  tier: Tier
}

export interface HistogramBucket {
  bucket: string
  count: number
  lo: number
  hi: number | null
}

export interface ReadinessSummary {
  threshold: number
  tier_red_max: number
  n_classes: number
  n_green: number
  n_warn: number
  n_red: number
  histogram: HistogramBucket[]
}

export interface ReadinessResponse {
  summary: ReadinessSummary
  classes: ClassReadiness[]
}

// ─── Section 3 — Wild diversity ────────────────────────────────────────

export interface DiversityBucket {
  n_marketplaces: number
  n_classes: number
}

export interface DiversityResponse {
  buckets: DiversityBucket[]
  top_marketplaces_7d: { marketplace: string; kept: number }[]
  suspicious_singletons: number
}

// ─── Section 4 — Cohorts ───────────────────────────────────────────────

export interface CohortRow {
  id: string
  name: string
  status: string
  zone: string | null
  n_members: number
  frozen_at: string | null
  created_at: string
}

export interface CohortResponse {
  n_draft: number
  n_frozen: number
  cohorts: CohortRow[]
}

// ─── Fetch helpers ─────────────────────────────────────────────────────

async function json<T>(path: string): Promise<T> {
  const resp = await fetch(`${ML_API}${path}`, {
    headers: { 'Content-Type': 'application/json' },
  })
  if (!resp.ok) {
    const body = await resp.text().catch(() => '')
    throw new Error(`${resp.status} ${resp.statusText}: ${body}`)
  }
  return resp.json() as Promise<T>
}

export function fetchPulse(windowDays = 7): Promise<PulseResponse> {
  return json<PulseResponse>(`/operations/pulse?window_days=${windowDays}`)
}

export function fetchReadiness(opts?: {
  tier?: Tier
  country?: string
  limit?: number
}): Promise<ReadinessResponse> {
  const params = new URLSearchParams()
  if (opts?.tier) params.set('tier', opts.tier)
  if (opts?.country) params.set('country', opts.country)
  if (opts?.limit !== undefined) params.set('limit', String(opts.limit))
  const qs = params.toString()
  return json<ReadinessResponse>(`/operations/training-readiness${qs ? `?${qs}` : ''}`)
}

export function fetchDiversity(): Promise<DiversityResponse> {
  return json<DiversityResponse>('/operations/wild-diversity')
}

export function fetchCohorts(): Promise<CohortResponse> {
  return json<CohortResponse>('/operations/cohorts')
}
