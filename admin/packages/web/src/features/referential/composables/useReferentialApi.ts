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

// ─── Coverage JO / EUR-Lex ─────────────────────────────────────────────

export interface JoCoverageCell {
  n_coins: number
  n_jo: number
  n_issued: number
}

export interface JoCoverageResponse {
  current_year: number
  years: number[]
  countries: string[]
  // country → { "2024": cell, … }
  cells: Record<string, Record<string, JoCoverageCell>>
  summary: { total_coins: number; total_jo: number; total_gap: number }
}

export function fetchJoCoverage(): Promise<JoCoverageResponse> {
  return json<JoCoverageResponse>('/referential/jo-coverage')
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

// ─── Zero-canon résiduels (BCE-aware) ─────────────────────────────────

export interface ZeroCanonEntry {
  eurio_id: string
  country: string
  year: number
  theme: string | null
  numista_id: number | null
}

export interface ZeroCanonResponse {
  n_db_zero_canon: number
  n_covered_by_bce_fs: number
  n_residuals: number
  residuals: ZeroCanonEntry[]
}

export function fetchZeroCanon(): Promise<ZeroCanonResponse> {
  return json<ZeroCanonResponse>('/referential/zero-canon')
}

// ─── Divergences BCE ↔ Numista ────────────────────────────────────────

export interface DivergenceFieldDiff {
  field: 'country' | 'year' | 'theme'
  numista_value: string | null
  bce_value: string | null
  similarity: number | null
}

export interface DivergenceEntry {
  eurio_id: string
  severity: 'hard' | 'soft'
  country: string
  year: number
  numista_theme: string | null
  bce_feature: string | null
  diffs: DivergenceFieldDiff[]
  bce_run_id: string | null
  bce_page_url: string | null
  numista_id: number | null
}

export interface DivergencesResponse {
  n_matched_bce: number
  n_hard: number
  n_soft: number
  n_clean: number
  soft_threshold: number
  divergences: DivergenceEntry[]
}

export function fetchDivergences(softThreshold?: number): Promise<DivergencesResponse> {
  const q = softThreshold != null ? `?soft_threshold=${softThreshold}` : ''
  return json<DivergencesResponse>(`/referential/divergences${q}`)
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

// ─── Fix proposals (chunk apply référentiel) ──────────────────────────

export interface FixProposalSummary {
  case_id: string
  country: string
  year: number
  shape: string
  confidence: string
  swap_eurio_id: string | null
  swap_current_numista_id: number | null
  swap_new_numista_id: number | null
  new_row_eurio_id: string
  new_row_numista_id: number
  n_warnings: number
}

export interface FixProposalsListResponse {
  generated_at: string | null
  n_proposals: number
  by_shape: Record<string, number>
  by_confidence: Record<string, number>
  proposals: FixProposalSummary[]
}

export interface FixProposalSwap {
  eurio_id: string
  current_numista_id: number
  new_numista_id: number
  current_numista_title: string
  new_numista_title: string
  current_similarity: number
  new_similarity: number
}

export interface FixProposalNewRow {
  eurio_id: string
  country: string
  year: number
  face_value: number
  numista_id: number
  theme: string | null
  design_description: string | null
}

export interface FixProposalSourceAttribution {
  source: string
  current_holder: string
  feature_text: string | null
  sim_to_existing_slug: number
  sim_to_new_slug: number
  recommended_target: 'existing' | 'new' | 'unknown'
}

export interface FixProposalDetail {
  case_id: string
  country: string
  year: number
  shape: string
  confidence: string
  reasoning: string
  swap: FixProposalSwap | null
  new_row: FixProposalNewRow
  source_attributions: FixProposalSourceAttribution[]
  warnings: string[]
}

export interface FixApplyStep {
  name: string
  status: 'ok' | 'failed' | 'skipped'
  diagnostic: Record<string, unknown>
}

export interface FixApplyResponse {
  case_id: string
  success: boolean
  started_at: string
  finished_at: string
  duration_sec: number
  steps: FixApplyStep[]
  backup_path: string | null
}

export interface FixProposalsRefreshResponse {
  started_at: string
  finished_at: string
  duration_sec: number
  generated_at: string | null
  n_proposals: number
  by_shape: Record<string, number>
  by_confidence: Record<string, number>
}

export function fetchFixProposals(): Promise<FixProposalsListResponse> {
  return json<FixProposalsListResponse>('/referential/fix-proposals')
}

export function fetchFixProposalDetail(caseId: string): Promise<FixProposalDetail> {
  return json<FixProposalDetail>(`/referential/fix-proposals/${encodeURIComponent(caseId)}`)
}

export function refreshFixProposals(): Promise<FixProposalsRefreshResponse> {
  return json<FixProposalsRefreshResponse>('/referential/fix-proposals/refresh', { method: 'POST' })
}

export function applyFixProposal(caseId: string): Promise<FixApplyResponse> {
  return json<FixApplyResponse>(
    `/referential/fix-proposals/${encodeURIComponent(caseId)}/apply`,
    { method: 'POST' },
  )
}
