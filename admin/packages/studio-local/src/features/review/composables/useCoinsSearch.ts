// Coin search composable — backs the /coins/search modal.
//
// Source = table `coins` de **eurio.db** via l'API ML (`GET /coins`), pas
// Supabase (doctrine SQLite-only — Supabase coins est périmé/vide, ce qui
// renvoyait « aucune pièce »). Le selector UI manipule un `denomination`
// synthétique ('1c'…'2eur-comm') traduit en {face_value, is_commemorative}.

import { eurioApi } from '@/shared/api/eurio-api'

// Sous-ensemble de la réponse `GET /coins` (CoinDetail) utilisé ici.
interface CoinDetailLite {
  eurio_id: string
  country: string
  year: number
  is_commemorative: boolean
  numista_id: number | null
}

export interface CoinSearchEntry {
  eurio_id: string
  country: string
  denomination: string
  year: number
  label: string
  canonical_thumb_url: string | null
  is_commemorative: boolean
}

export interface CoinSearchFilters {
  country: string | null
  denomination: string | null
  year: number | null
  limit?: number
}

// ─── Constantes UX ──────────────────────────────────────────────────────
//
// 21 pays eurozone + 4 micro-États (AD, MC, SM, VA), triés alphabétiquement
// par code ISO — comme la liste `COUNTRIES` de CoinsPage.vue.

export const EURO_COUNTRIES: { code: string; label: string; flag: string }[] = [
  { code: 'AD', label: 'Andorre',     flag: '🇦🇩' },
  { code: 'AT', label: 'Autriche',    flag: '🇦🇹' },
  { code: 'BE', label: 'Belgique',    flag: '🇧🇪' },
  { code: 'BG', label: 'Bulgarie',    flag: '🇧🇬' },
  { code: 'CY', label: 'Chypre',      flag: '🇨🇾' },
  { code: 'DE', label: 'Allemagne',   flag: '🇩🇪' },
  { code: 'EE', label: 'Estonie',     flag: '🇪🇪' },
  { code: 'ES', label: 'Espagne',     flag: '🇪🇸' },
  { code: 'FI', label: 'Finlande',    flag: '🇫🇮' },
  { code: 'FR', label: 'France',      flag: '🇫🇷' },
  { code: 'GR', label: 'Grèce',       flag: '🇬🇷' },
  { code: 'HR', label: 'Croatie',     flag: '🇭🇷' },
  { code: 'IE', label: 'Irlande',     flag: '🇮🇪' },
  { code: 'IT', label: 'Italie',      flag: '🇮🇹' },
  { code: 'LT', label: 'Lituanie',    flag: '🇱🇹' },
  { code: 'LU', label: 'Luxembourg',  flag: '🇱🇺' },
  { code: 'LV', label: 'Lettonie',    flag: '🇱🇻' },
  { code: 'MC', label: 'Monaco',      flag: '🇲🇨' },
  { code: 'MT', label: 'Malte',       flag: '🇲🇹' },
  { code: 'NL', label: 'Pays-Bas',    flag: '🇳🇱' },
  { code: 'PT', label: 'Portugal',    flag: '🇵🇹' },
  { code: 'SI', label: 'Slovénie',    flag: '🇸🇮' },
  { code: 'SK', label: 'Slovaquie',   flag: '🇸🇰' },
  { code: 'SM', label: 'Saint-Marin', flag: '🇸🇲' },
  { code: 'VA', label: 'Vatican',     flag: '🇻🇦' },
]

export const DENOMINATIONS: { value: string; label: string; faceValue: number; commemorative: boolean }[] = [
  { value: '1c',        label: '1 cent',      faceValue: 0.01, commemorative: false },
  { value: '2c',        label: '2 cents',     faceValue: 0.02, commemorative: false },
  { value: '5c',        label: '5 cents',     faceValue: 0.05, commemorative: false },
  { value: '10c',       label: '10 cents',    faceValue: 0.10, commemorative: false },
  { value: '20c',       label: '20 cents',    faceValue: 0.20, commemorative: false },
  { value: '50c',       label: '50 cents',    faceValue: 0.50, commemorative: false },
  { value: '1eur',      label: '1 €',         faceValue: 1,    commemorative: false },
  { value: '2eur',      label: '2 €',         faceValue: 2,    commemorative: false },
  { value: '2eur-comm', label: '2 € commémo', faceValue: 2,    commemorative: true  },
]

export const YEAR_RANGE = { min: 1999, max: 2026 }

// ─── Fetcher API ML (eurio.db) ──────────────────────────────────────────

export async function searchCoins(filters: CoinSearchFilters): Promise<CoinSearchEntry[]> {
  if (!filters.country) return []
  if (!filters.denomination) return []

  const denomMeta = DENOMINATIONS.find((d) => d.value === filters.denomination)
  if (!denomMeta) return []

  const limit = filters.limit ?? 60

  // `GET /coins` filtre fv + commemo + country (CSV ISO2 majuscule, comme
  // eurio.db). Pas de filtre année côté API → on filtre client-side (l'année
  // est optionnelle dans le selector). Les variantes sont exclues par défaut.
  const params = new URLSearchParams({
    fv: String(denomMeta.faceValue),
    commemo: denomMeta.commemorative ? '1' : '0',
    country: filters.country,
    limit: String(limit),
  })
  // Sur `eurio-api` et non le ML local : la recherche libre est LE geste qui suit
  // un « DINO s'est trompé », elle doit donc marcher à distance. `coins_routes`
  // est monté sur l'image lean, et cet appel a besoin de l'auth.
  const data = await eurioApi.get<{ items: CoinDetailLite[] }>(
    `/coins?${params.toString()}`,
  )

  const countryMeta = EURO_COUNTRIES.find((c) => c.code === filters.country)
  return (data.items ?? [])
    .filter((coin) => filters.year === null || coin.year === filters.year)
    .sort((a, b) => a.year - b.year || a.eurio_id.localeCompare(b.eurio_id))
    .map((coin) => ({
      eurio_id: coin.eurio_id,
      country: coin.country,
      denomination: filters.denomination!,
      year: coin.year,
      label: `${countryMeta?.label ?? coin.country} · ${denomMeta.label} · ${coin.year}`,
      // Vignette canonique servie par l'API ML depuis MinIO (CDN redirect),
      // clé `eurio_id` — pas `numista_id` (endpoint legacy `/images/<nid>/source`
      // = layout `ml/datasets/` déprécié, absent des machines migrées).
      canonical_thumb_url: `${eurioApi.base}/referential/canonical/${coin.eurio_id}/obverse/thumb`,
      is_commemorative: coin.is_commemorative,
    }))
}

// ─── Text search (autocomplete eurio_id libre) ──────────────────────────
//
// Recherche full-text sur eurio_id + theme + country via GET /coins?search=.
// Utilisée par le champ autocomplete direct dans FreeSelectorPanel.vue pour
// le rescue cross-classe (saisir un eurio_id ou un mot-clé quelconque).

interface CoinDetail {
  eurio_id: string
  country: string
  country_name: string | null
  year: number
  face_value: number
  is_commemorative: boolean
  theme: string | null
  numista_id: number | null
}

export async function searchCoinsByText(
  query: string,
  opts?: { fv?: number; commemo?: boolean; limit?: number },
): Promise<CoinSearchEntry[]> {
  if (query.trim().length < 2) return []

  const limit = opts?.limit ?? 20
  const params = new URLSearchParams({
    search: query.trim(),
    limit: String(limit),
  })
  if (opts?.fv !== undefined) params.set('fv', String(opts.fv))
  if (opts?.commemo !== undefined) params.set('commemo', opts.commemo ? '1' : '0')

  const data = await eurioApi.get<{ items: CoinDetail[]; total: number }>(
    `/coins?${params.toString()}`,
  )

  return (data.items ?? []).map((coin) => {
    const fvLabel =
      coin.face_value < 1
        ? `${Math.round(coin.face_value * 100)}c`
        : `${coin.face_value}eur`
    const denomination = `${fvLabel}${coin.is_commemorative ? '-comm' : ''}`
    const label =
      (coin.country_name ?? coin.country) +
      ' · ' +
      (coin.theme ?? coin.eurio_id)
    return {
      eurio_id: coin.eurio_id,
      country: coin.country,
      denomination,
      year: coin.year,
      label,
      // Cf. searchCoins : vignette canonique par `eurio_id` (MinIO/CDN), pas
      // l'endpoint legacy `numista_id`.
      canonical_thumb_url: `${eurioApi.base}/referential/canonical/${coin.eurio_id}/obverse/thumb`,
      is_commemorative: coin.is_commemorative,
    }
  })
}

// ─── Fuzzy search (combobox `/`) ────────────────────────────────────────

export async function fuzzySearchCoins(query: string): Promise<CoinSearchEntry[]> {
  const q = query.trim().toLowerCase()
  if (q.length < 2) return []

  const tokens = q.split(/\s+/)
  let country: string | null = null
  let denomination: string | null = null
  let year: number | null = null

  for (const t of tokens) {
    const upper = t.toUpperCase()
    if (EURO_COUNTRIES.some((c) => c.code === upper)) {
      country = upper
      continue
    }
    const lower = t.toLowerCase()
    const labelMatch = EURO_COUNTRIES.find((c) => c.label.toLowerCase().startsWith(lower))
    if (labelMatch && !country) {
      country = labelMatch.code
      continue
    }
    const yr = parseInt(t, 10)
    if (!isNaN(yr) && yr >= YEAR_RANGE.min && yr <= YEAR_RANGE.max) {
      year = yr
      continue
    }
    if (t === '1' || t === '2') {
      denomination = `${t}eur`
      continue
    }
    if (t.endsWith('c') && !isNaN(parseInt(t, 10))) {
      denomination = t
      continue
    }
    if (t === 'comm' || t === 'commemo') {
      denomination = '2eur-comm'
      continue
    }
  }

  if (!country) return []
  if (!denomination) denomination = '2eur'
  return searchCoins({ country, denomination, year, limit: 60 })
}
