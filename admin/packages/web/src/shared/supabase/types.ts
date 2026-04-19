/**
 * Domain types — types métier indépendants des types générés.
 * Les pages castent les résultats Supabase (`as Coin[]`, `as Set[]`) parce que
 * Supabase JS retourne `Json` pour les JSONB et on narrow-type ici.
 *
 * Toujours importer depuis ce fichier, jamais depuis database.generated.ts.
 */
import type { Database as DatabaseGenerated, Json } from './database.generated'

export type { Json }
export type Database = DatabaseGenerated

// ───────── Enums ─────────

export type IssueType =
  | 'circulation'
  | 'commemo-national'
  | 'commemo-common'
  | 'starter-kit'
  | 'bu-set'
  | 'proof'

export type SetKind = 'structural' | 'curated' | 'parametric'

export type SetCategory = 'country' | 'theme' | 'tier' | 'personal' | 'hunt'

export type SetAuditAction =
  | 'create'
  | 'update'
  | 'delete'
  | 'activate'
  | 'deactivate'
  | 'publish'

export type MintingEndReason =
  | 'ruler_change'
  | 'redesign'
  | 'policy'
  | 'sede_vacante_end'
  | 'other'

// ───────── JSONB shapes ─────────

export interface I18nField {
  fr: string
  en?: string
  de?: string
  it?: string
}

/**
 * DSL criteria structurel — figé v1 (sets-architecture.md §3).
 * AND implicite entre clés. Pas de OR, pas de range year.
 */
export interface SetCriteria {
  country?: string | string[]
  issue_type?: IssueType | IssueType[]
  year?: number | 'current'
  denomination?: number[]
  series_id?: string
  is_withdrawn?: boolean
  distinct_by?: 'country'
  min_mintage?: number
  max_mintage?: number
}

export interface SetReward {
  badge?: 'bronze' | 'silver' | 'gold'
  xp?: number
  level_bump?: boolean
}

/** Élément du array coins.images (JSONB) — ancien format */
export interface CoinImage {
  url: string
  role: 'obverse' | 'reverse' | 'edge' | 'detail' | string
  source: 'bce_comm' | 'numista' | 'mdp' | 'lmdlp' | string
  feature?: string
  fetched_at?: string
  description?: string
}

/** coins.images — nouveau format dict (enrichissement Numista) */
export interface CoinImageDict {
  obverse?: string
  obverse_thumb?: string
  reverse?: string
  reverse_thumb?: string
}

/** coins.images peut être array (ancien) ou dict (nouveau) */
export type CoinImages = CoinImage[] | CoinImageDict

/** coins.cross_refs — union des clés observées en prod */
export interface CoinCrossRefs {
  wikipedia_url?: string
  lmdlp_url?: string
  lmdlp_skus?: string[]
  mdp_urls?: string[]
  mdp_skus?: string[]
  numista_id?: number
  numista_url?: string
}

// ───────── Domain entities ─────────
// Standalone interfaces — pas dérivées des Row pour éviter la complexité des
// conditional types Supabase. Gardées alignées à la main sur database.generated.ts.

export interface Coin {
  eurio_id: string
  country: string
  year: number
  face_value: number
  currency: string
  theme: string | null
  design_description: string | null
  design_group_id: string | null
  is_commemorative: boolean
  collector_only: boolean
  issue_type: IssueType | null
  series_id: string | null
  mintage: number | null
  is_withdrawn: boolean
  withdrawn_at: string | null
  withdrawal_reason: string | null
  images: CoinImages
  cross_refs: CoinCrossRefs
  national_variants: Record<string, unknown> | null
  sources_used: string[]
  needs_review: boolean
  review_reason: string | null
  first_seen: string
  last_updated: string
}

export interface CoinSeries {
  id: string
  country: string
  designation: string
  designation_i18n: I18nField | null
  description: string | null
  minting_started_at: string
  minting_ended_at: string | null
  minting_end_reason: MintingEndReason | null
  supersedes_series_id: string | null
  superseded_by_series_id: string | null
  created_at: string
  updated_at: string
}

export interface Set {
  id: string
  kind: SetKind
  category: SetCategory
  name_i18n: I18nField
  description_i18n: I18nField | null
  criteria: SetCriteria | null
  param_key: string | null
  reward: SetReward | null
  display_order: number
  icon: string | null
  expected_count: number | null
  active: boolean
  created_at: string
  updated_at: string
}

export interface SetMember {
  set_id: string
  eurio_id: string
  position: number | null
}

export interface SetAudit {
  id: number
  set_id: string
  action: SetAuditAction
  before: Json | null
  after: Json | null
  actor: string
  at: string
}

// ───────── Confusion map (Phase 1 ML scalability) ─────────

export type ConfusionZone = 'green' | 'orange' | 'red'

export interface ConfusionNeighbor {
  eurio_id: string
  similarity: number
  obverse_url: string | null
}

export interface ConfusionMapRow {
  id: number
  eurio_id: string
  encoder_version: string
  nearest_eurio_id: string | null
  nearest_similarity: number
  top_k_neighbors: ConfusionNeighbor[]
  zone: ConfusionZone
  computed_at: string
}
