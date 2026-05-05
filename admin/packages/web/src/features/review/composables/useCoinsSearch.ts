// Coin search composable — backs the /coins/search modal.
//
// Source = table `coins` Supabase (même source que /coins page).
// Le selector UI manipule un `denomination` synthétique ('1c'…'2eur-comm')
// qui se traduit en {face_value, is_commemorative} pour la requête.

import { supabase } from '@/shared/supabase/client'
import type { Coin } from '@/shared/supabase/types'
import { firstImageUrl } from '@/shared/utils/coin-images'

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

// ─── Fetcher Supabase ───────────────────────────────────────────────────

export async function searchCoins(filters: CoinSearchFilters): Promise<CoinSearchEntry[]> {
  if (!filters.country) return []
  if (!filters.denomination) return []

  const denomMeta = DENOMINATIONS.find((d) => d.value === filters.denomination)
  if (!denomMeta) return []

  const limit = filters.limit ?? 60

  let q = supabase
    .from('coins')
    .select('eurio_id, country, year, face_value, is_commemorative, theme, images')
    .eq('country', filters.country)
    .eq('face_value', denomMeta.faceValue)
    .eq('is_commemorative', denomMeta.commemorative)
    .order('year', { ascending: true })
    .order('eurio_id', { ascending: true })
    .limit(limit)

  if (filters.year !== null) q = q.eq('year', filters.year)

  const { data, error } = await q
  if (error) throw error

  const countryMeta = EURO_COUNTRIES.find((c) => c.code === filters.country)
  return (data ?? []).map((row) => {
    const coin = row as unknown as Coin
    return {
      eurio_id: coin.eurio_id,
      country: coin.country,
      denomination: filters.denomination!,
      year: coin.year,
      label: `${countryMeta?.label ?? coin.country} · ${denomMeta.label} · ${coin.year}`,
      canonical_thumb_url: firstImageUrl(coin),
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
