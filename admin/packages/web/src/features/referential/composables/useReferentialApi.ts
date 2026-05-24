// Referential API — coverage + heal + (à venir) discover + push.
// Backend: ml/api/referential_routes.py.

import { ML_API } from '@/features/training/composables/useTrainingApi'

export interface CoverageYear {
  year: number
  n_bce_listed: number
  n_eurio_db: number
  n_with_canonical: number
  n_with_local_image: number
  n_missing_canonical: number
  bce_unmatched_count: number
}

export interface GapEntry {
  eurio_id: string
  country: string
  year: number
  theme: string | null
  numista_id: number | null
}

export interface BceOnlyEntry {
  country: string
  year: number
  feature: string
  image_url: string
}

export interface CoverageResponse {
  summary: {
    n_bce_listed_total: number
    n_eurio_db_total: number
    n_with_canonical_total: number
    n_with_local_image_total: number
    n_missing_canonical: number
    n_missing_payload: number
    n_missing_local_image: number
    n_bce_only: number
  }
  by_year: CoverageYear[]
  gaps_missing_canonical: GapEntry[]
  gaps_missing_payload: GapEntry[]
  gaps_missing_local_image: GapEntry[]
  bce_only: BceOnlyEntry[]
}

export interface HealResponse {
  started_at: string
  finished_at: string
  duration_sec: number
  enrich_payloads: Record<string, unknown>
  migrate_canonical_schema: Record<string, unknown>
  migrate_local_images: Record<string, unknown>
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${ML_API}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!resp.ok) {
    const body = await resp.text().catch(() => '')
    throw new Error(`${resp.status} ${resp.statusText}: ${body}`)
  }
  return resp.json() as Promise<T>
}

export function fetchCoverage(): Promise<CoverageResponse> {
  return json<CoverageResponse>('/referential/coverage')
}

export function runHeal(): Promise<HealResponse> {
  return json<HealResponse>('/referential/heal', { method: 'POST' })
}

// ─── Discover (Numista oracle sweep) ───────────────────────────────────

export interface DiscoverRequest {
  year_from?: number
  year_to?: number
  countries?: string[]
}

export interface DiscoverResponse {
  started_at: string
  finished_at: string
  duration_sec: number
  year_from: number
  year_to: number
  discover_numista: Record<string, unknown>
  cascade_images: Record<string, unknown> | null
}

export function runDiscover(req?: DiscoverRequest): Promise<DiscoverResponse> {
  return json<DiscoverResponse>('/referential/discover', {
    method: 'POST',
    body: JSON.stringify(req ?? {}),
  })
}

// ─── Joint issues ──────────────────────────────────────────────────────

export interface JointIssue {
  design_group_id: string
  designation: string
  year: number
  n_expected: number
  n_in_db: number
  n_with_canonical: number
  n_with_local_image: number
  countries_in_db: string[]
  countries_missing: string[]
  countries_unexpected: string[]
}

export interface JointIssuesResponse {
  joint_issues: JointIssue[]
}

export function fetchJointIssues(): Promise<JointIssuesResponse> {
  return json<JointIssuesResponse>('/referential/joint-issues')
}

// ─── Push to Supabase ──────────────────────────────────────────────────

export interface PushResponse {
  started_at: string
  finished_at: string
  duration_sec: number
  summary: Record<string, unknown>
}

export function runPush(): Promise<PushResponse> {
  return json<PushResponse>('/referential/push', { method: 'POST' })
}
