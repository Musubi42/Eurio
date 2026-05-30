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
  topics?: CoinTopicDetail[]
}

export interface CoinTopicDetail {
  source: string       // 'numista_api' | 'bce_official' | …
  lang: string
  topic: string
  method?: string | null
  confidence?: string
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

export interface CoinDescription {
  lang: string
  title: string
  description: string | null
  source: string
  method: string | null
  confidence: string | null
  model: string | null
}

export interface DescriptionsResponse {
  descriptions: CoinDescription[]
}

export type SourceState = 'never' | 'ok' | 'empty_upstream' | 'error'

export interface SourceStatusEntry {
  source: string
  state: SourceState
  axes: Record<string, unknown>
  last_checked_at: string | null
  last_run_id: string | null
  updated_at: string | null
}

export interface SourceStatusResponse {
  eurio_id: string
  sources: SourceStatusEntry[]
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

// ─── Caractéristiques : observations + crédits (extraction riche Numista) ──

export interface CoinObservation {
  observation_type: string
  value: unknown
  source: string
  source_ref: string | null
  recorded_at: string | null
}

export interface ObservationsResponse {
  observations: CoinObservation[]
  composition: string | null
  weight_g: number | null
  diameter_mm: number | null
  thickness_mm: number | null
  shape: string | null
  orientation: string | null
  edge_description: string | null
  edge_lettering: string | null
  edge_lettering_translation: string | null
  obverse_lettering: string | null
  reverse_lettering: string | null
  is_demonetized: boolean | null
}

export interface CreditEntry {
  name: string
  source: string
  source_ref: string | null // 'obverse' | 'reverse'
  position: number
}

export interface CreditsResponse {
  designers: CreditEntry[]
  engravers: CreditEntry[]
  sculptors: CreditEntry[]
}

export interface MintReleaseObservation {
  fact_type: string // 'mintage' | …
  value: unknown
  source: string
}

export interface MintReleasePriceEntry {
  grade_raw: string
  grade_eurio: string | null
  price: number
  currency: string
  source: string
  fetched_at: string
}

export interface MintReleaseFull {
  id: string
  mint_year: number
  mint_id: string | null
  issue_type: string
  notes: string | null
  observations: MintReleaseObservation[]
  prices: MintReleasePriceEntry[]
}

export interface MintReleasesFullResponse {
  mint_releases: MintReleaseFull[]
}

export type SourceKey = 'numista' | 'bce' | 'wikipedia' | 'lmdlp' | 'ebay'

export interface CoinListResponse {
  items: CoinDetail[]
  total: number
}

export interface CoinListFilters {
  fv?: number
  country?: string[]
  commemo?: boolean
  has_bce?: boolean
  has_ebay?: boolean
  has_lmdlp?: boolean
  has_wikipedia?: boolean
  has_numista?: boolean
  in_design_group?: boolean
  include_variants?: boolean
  personal_owned?: boolean
  lent_to_me?: boolean
  search?: string
  eurio_ids?: string[]
  offset?: number
  limit?: number
}

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

// ─── List + filters ───────────────────────────────────────────────────────

export function fetchCoinsList(filters: CoinListFilters = {}): Promise<CoinListResponse> {
  const params = new URLSearchParams()
  if (filters.fv != null) params.set('fv', String(filters.fv))
  if (filters.country?.length) params.set('country', filters.country.join(','))
  if (filters.commemo != null) params.set('commemo', filters.commemo ? '1' : '0')
  if (filters.has_bce != null) params.set('has_bce', String(filters.has_bce))
  if (filters.has_ebay != null) params.set('has_ebay', String(filters.has_ebay))
  if (filters.has_lmdlp != null) params.set('has_lmdlp', String(filters.has_lmdlp))
  if (filters.has_wikipedia != null) params.set('has_wikipedia', String(filters.has_wikipedia))
  if (filters.has_numista != null) params.set('has_numista', String(filters.has_numista))
  if (filters.in_design_group != null) params.set('in_design_group', String(filters.in_design_group))
  if (filters.include_variants) params.set('include_variants', 'true')
  if (filters.personal_owned != null) params.set('personal_owned', String(filters.personal_owned))
  if (filters.lent_to_me != null) params.set('lent_to_me', String(filters.lent_to_me))
  if (filters.search) params.set('search', filters.search)
  if (filters.eurio_ids?.length) params.set('eurio_ids', filters.eurio_ids.join(','))
  if (filters.offset != null) params.set('offset', String(filters.offset))
  if (filters.limit != null) params.set('limit', String(filters.limit))
  const qs = params.toString()
  return json<CoinListResponse>(`/coins${qs ? '?' + qs : ''}`)
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

export function fetchCoinDescriptions(eurioId: string): Promise<DescriptionsResponse> {
  return json<DescriptionsResponse>(`/coins/${encodeURIComponent(eurioId)}/descriptions`)
}

export function fetchCoinSourceStatus(eurioId: string): Promise<SourceStatusResponse> {
  return json<SourceStatusResponse>(`/coins/${encodeURIComponent(eurioId)}/source-status`)
}

export interface RefreshResponse {
  run_id: string
  source: string
  status: string
}

export function postCoinRefresh(eurioId: string, source: 'bce' | 'numista'): Promise<RefreshResponse> {
  return json<RefreshResponse>(
    `/coins/${encodeURIComponent(eurioId)}/refresh?source=${source}`,
    { method: 'POST' },
  )
}

// Snapshot léger d'un run pour le polling du refresh par coin (découplé du type
// SourceId de la feature sources, qui ne couvre pas 'numista').
export interface RunSnapshotLite {
  status: 'running' | 'success' | 'partial' | 'failed'
  current_step: string | null
  error_summary: string | null
}

export function fetchRunSnapshot(source: string, runId: string): Promise<RunSnapshotLite> {
  return json<RunSnapshotLite>(`/sources/${source}/runs/${encodeURIComponent(runId)}`)
}

export function fetchCoinPrices(eurioId: string): Promise<PricesResponse> {
  return json<PricesResponse>(`/coins/${encodeURIComponent(eurioId)}/prices`)
}

export function fetchCoinObservations(eurioId: string): Promise<ObservationsResponse> {
  return json<ObservationsResponse>(`/coins/${encodeURIComponent(eurioId)}/observations`)
}

export function fetchCoinCredits(eurioId: string): Promise<CreditsResponse> {
  return json<CreditsResponse>(`/coins/${encodeURIComponent(eurioId)}/credits`)
}

export function fetchCoinMintReleasesFull(eurioId: string): Promise<MintReleasesFullResponse> {
  return json<MintReleasesFullResponse>(`/coins/${encodeURIComponent(eurioId)}/mint-releases-full`)
}

// ─── Variantes (chantier variantes) ─────────────────────────────────────────

export interface VariantGroupEntry {
  eurio_id: string
  variant_kind: string
  variant_label: string | null
  title: string | null
  is_self: boolean
}
export interface VariantGroupResponse {
  canonical_eurio_id: string
  members: VariantGroupEntry[]
}

export function fetchCoinVariantGroup(eurioId: string): Promise<VariantGroupResponse> {
  return json<VariantGroupResponse>(`/coins/${encodeURIComponent(eurioId)}/variant-group`)
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
