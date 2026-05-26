// Coins API — thin fetch wrappers vers ml/api/coins_routes.py.
//
// P.8b du chantier coin-richness : remplace les reads Supabase directs
// (useCoinLookups.ts, CoinDetailPage.vue) par des calls FastAPI.
// Doctrine SQLite-only — eurio.db est la source de vérité.
//
// Backend : ml/api/coins_routes.py.

import { ML_API } from '@/features/training/composables/useTrainingApi'

// ─── Models (alignés sur Pydantic côté backend) ──────────────────────────

export interface CoinImage {
  role: string
  source: string
  url: string | null
  local_path: string | null
}

export interface CoinDetail {
  eurio_id: string
  country: string
  country_name: string | null
  year: number
  face_value: number
  currency: string
  is_commemorative: boolean
  theme: string | null
  numista_id: number | null
  design_description: string | null
  design_group_id: string | null
  series_id: string | null
  personal_owned: boolean
  lent_to_me: boolean
  needs_review: boolean
  images: CoinImage[]
  cross_refs: Record<string, string>
  sources_used: string[]
  has_bce: boolean
  has_ebay: boolean
  has_lmdlp: boolean
  has_wikipedia: boolean
}

export interface I18nName {
  lang: string
  title: string
  source: string
  method: string | null
  confidence: string | null
  model: string | null
}

export interface I18nAlias {
  lang: string
  alias: string
  source: string
  method: string | null
  confidence: string | null
}

export interface I18nResponse {
  names: I18nName[]
  aliases: I18nAlias[]
}

export interface TypeLevelPrice {
  source: string
  condition_normalized: string
  condition_raw: string | null
  currency: string
  p10: number | null
  p50: number | null
  p90: number | null
  sample_size: number
  period_start: string
  period_end: string
}

export interface MintReleasePrice {
  mint_release_id: string
  parent_type_id: string
  mint_id: string | null
  mint_year: number
  issue_type: string
  source: string
  grade_raw: string
  grade_eurio: string | null
  price: number
  currency: string
  fetched_at: string
}

export interface PricesResponse {
  type_level: TypeLevelPrice[]
  mint_release_level: MintReleasePrice[]
}

export interface CoinSeries {
  id: string
  country: string
  designation: string
  designation_i18n: Record<string, string> | null
  description: string | null
  minting_started_at: string
  minting_ended_at: string | null
  minting_end_reason: string | null
}

export interface CoinPatch {
  personal_owned?: boolean
  lent_to_me?: boolean
}

export type SourceKey = 'numista' | 'bce' | 'wikipedia' | 'lmdlp' | 'ebay'

// ─── Helpers ──────────────────────────────────────────────────────────────

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

// ─── Lookups ──────────────────────────────────────────────────────────────

export function fetchTrainedEurioIds(): Promise<string[]> {
  return json<string[]>('/coins/lookups/trained')
}

export function fetchSourceCounts(): Promise<Partial<Record<SourceKey, number>>> {
  return json<Partial<Record<SourceKey, number>>>('/coins/lookups/source-counts')
}

// ─── Coin detail + sub-resources ──────────────────────────────────────────

export function fetchCoin(eurioId: string): Promise<CoinDetail> {
  return json<CoinDetail>(`/coins/${encodeURIComponent(eurioId)}`)
}

export function fetchCoinI18n(eurioId: string): Promise<I18nResponse> {
  return json<I18nResponse>(`/coins/${encodeURIComponent(eurioId)}/i18n`)
}

export function fetchCoinPrices(eurioId: string): Promise<PricesResponse> {
  return json<PricesResponse>(`/coins/${encodeURIComponent(eurioId)}/prices`)
}

export function fetchCoinEmbedding(eurioId: string): Promise<{ model_version: string | null }> {
  return json<{ model_version: string | null }>(`/coins/${encodeURIComponent(eurioId)}/embedding`)
}

export function fetchCoinSeries(eurioId: string): Promise<CoinSeries | null> {
  return json<CoinSeries | null>(`/coins/${encodeURIComponent(eurioId)}/series`)
}

export function patchCoin(eurioId: string, patch: CoinPatch): Promise<CoinDetail> {
  return json<CoinDetail>(`/coins/${encodeURIComponent(eurioId)}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}
