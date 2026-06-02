/* api/types.ts — CONTRAT DE DONNÉES VIVANT du proto.
 *
 * Tout ce que l'app CONSOMME (pas ce qu'elle produit). Frontière stricte :
 * aucun champ owned/condition/addedAt ici — ça vit dans le store `collection`.
 * Ces types sont l'interface de la future vraie API → Supabase (cf.
 * docs/research/supabase-app-schema-v2.md). En mode fixtures ils sont backés
 * par data/app_core.json ; en mode live, par les mêmes shapes côté Supabase.
 */

// ───────── Snapshot brut (sortie de loadSnapshot) ─────────
// Shape de data/app_core.json (schema_version 2). Le contact avec le chantier
// eurio.db = ce type + le loader. Si la shape bouge, c'est ici qu'on le voit.

export interface RawCoin {
  eurio_id: string
  country: string
  country_name: string
  year: number | null
  face_value_cents: number
  is_commemorative: boolean
  collector_only?: boolean
  theme: string | null
  design_description: string | null
  mintage?: number | null
  diameter_mm?: number | null
  weight_g?: number | null
  thickness_mm?: number | null
  composition?: string | null
  shape?: string | null
  orientation?: string | null
  edge_description?: string | null
  edge_lettering?: string | null
  obverse_lettering?: string | null
  reverse_lettering?: string | null
  demonetized?: boolean
  demonetized_on?: string | null
  design_group_id?: string | null
  variant_kind?: string | null
  canonical_eurio_id?: string | null
  series_id?: string | null
  shared_reverse_id?: string | null
  /** URL/chemin de l'avers (live = coin_image.storage_path). Absent en fixtures
   *  → résolu par convention de chemin Storage (cf. loader.obverseUrl). */
  obverse_image_url?: string | null
  names?: Record<string, string>
  descriptions?: Record<string, string>
  prices?: RawPrice[]
  credits?: unknown
  topics?: unknown[]
  mint_releases?: unknown[]
  observations?: { wikipedia?: { mintage_total?: number | null } }
  provenance?: { sources_used?: string[]; last_updated?: string }
}

/** Cote marché brute par qualité (cents), telle que sérialisée dans le core. */
export interface RawPrice {
  grade: string
  p_low: number | null
  p_mid: number | null
  p_high: number | null
  currency?: string | null
  source?: string | null
  sampled_at?: string | null
}

export interface RawSharedReverse {
  id: string
  asset_name: string
  [k: string]: unknown
}

export interface Snapshot {
  schema_version: number
  generated_at?: string
  offline_langs?: string[]
  coin_count?: number
  coins: RawCoin[]
  shared_reverse?: RawSharedReverse[]
  design_groups?: unknown[]
  mints?: unknown[]
}

// ───────── Entité catalogue (à plat, consommée par les vues) ─────────

export interface Coin {
  eurioId: string
  country: string            // iso minuscule, ex 'at'
  countryName: string
  year: number | null
  faceValueCents: number
  faceValue: number          // euros, ex 2 | 0.5
  isCommemorative: boolean
  collectorOnly: boolean
  theme: string | null
  designDescription: string | null
  variantKind: string | null
  canonicalEurioId: string | null
  designGroupId: string | null
  sharedReverseId: string | null
  /** Avers résolu : URL fournie par le contrat (live) ou null → convention Storage. */
  obverseImageUrl: string | null
  mintage: number | null
  diameterMm: number | null
  weightG: number | null
  composition: string | null
  edgeDescription: string | null
  demonetized: boolean
  names: Record<string, string>
  descriptions: Record<string, string>
  topics: unknown[]
  credits: unknown
  /** Cotes marché réelles par qualité (euros via cents), vide si non dispo. */
  prices: CoinPrice[]
  mintReleases: unknown[]
  provenance: { sourcesUsed: string[]; lastUpdated: string | null }
  /** Enregistrement brut, pour les champs pas encore promus en surface typée. */
  raw: RawCoin
}

// ───────── Marché ─────────

export interface RarityTier {
  key: string
  label: string
  gold: boolean
}

/** Cote marché par qualité, montants en CENTS (tels que stockés). */
export interface CoinPrice {
  grade: string
  pLow: number | null
  pMid: number | null
  pHigh: number | null
  currency: string | null
}

/** Valeurs par qualité, en euros. */
export interface Grades {
  unc: number
  ttb: number
  tb: number
}

export interface Market {
  p25: number
  p50: number
  p75: number
  deltaVsFace: number              // %
  history: number[]                // points mensuels (peut être vide)
  delta3m: number | null           // %
  projection: { low: number; high: number } | null
  rarity: RarityTier
  grades: Grades
}

// ───────── Récit ─────────

export interface RecitChapter {
  eyebrow: string
  title: string
  body: string
}

export interface Recit {
  headline: string
  lead: string
  event: RecitChapter
  context: RecitChapter
  designers: RecitChapter
  place: RecitChapter
}

// ───────── Reveal post-scan ─────────
// total/grades/tier/nEffect = catalogue ; `owned` superposé par le store.

export interface Reveal {
  tier: string
  mintage: number
  grades: Grades
  nEffect: string
  narration: { line: string; long: string }
  completionTotal: number
  completionOwned: number          // démo (jointure store en live)
  accent: string                   // chip d'accroche (effet social/rareté)
}

// ───────── Progression pays (fixture démo — cf. sets) ─────────

export interface CountryProgress {
  iso: string                      // 'FR'
  name: string
  flag: string
  owned: number
  total: number
}

// ───────── Sets ─────────
// Note : tant que les sets ne référencent pas de vrais eurio_id (chantier
// data dédié), owned/scannedAt/completedAt sont des données DÉMO portées par
// la fixture (pas une jointure store). En live, la jointure prendra le relais.

export type CoinMetal = 'copper' | 'nordic' | 'silver' | 'bimetal'
export type SetCategory = 'country' | 'theme' | 'tier' | 'personal' | 'hunt'
export type SetKind = 'structural' | 'curated' | 'parametric'

/** Slot de la mini-planche d'aperçu (liste). metal null = case de padding. */
export interface PreviewSlot {
  metal: CoinMetal | 'missing' | null
  val: string
}

/** Carte de set dans la liste. */
export interface SetPreview {
  id: string
  title: string
  description: string
  category: SetCategory
  kind: SetKind
  owned: number
  total: number
  completedAt: string | null
  preview: PreviewSlot[]
}

/** Pièce d'une planche de détail. */
export interface SetCoin {
  eurioId: string
  metal: CoinMetal
  val: string
  owned: boolean
  scannedAt: string | null
}

/** Détail complet d'un set (planche). */
export interface SetDetail {
  id: string
  title: string                    // peut contenir <em>
  description: string
  kindLabel: string
  chips: string[]
  completedAt: string | null
  reward: { title: string }
  coins: SetCoin[]
}

// ───────── Planche pays (fixture démo — drill-down catalogue) ─────────

export interface PlancheCoin {
  eurioId: string
  type: 'circulation' | 'commemo'
  metal: CoinMetal
  val: string
  owned: boolean
  scannedAt: string | null
}

export interface CountryPlanche {
  iso: string
  name: string
  flag: string
  coins: PlancheCoin[]
}

// ───────── Assets 3D ─────────

export interface Coin3DAssets {
  obverse: string                  // URL Storage
  reverse: string                  // carte packagée
  edge: 'procedural'
  uv: { repeat: number; offset: number }
}

// ───────── Critères de filtre ─────────

export interface CoinFilter {
  country?: string
  year?: number
  faceValueCents?: number
  isCommemorative?: boolean
}

// ───────── Options coinSvg ─────────

export interface CoinSvgOpts {
  size?: number
  showLabel?: boolean
}
