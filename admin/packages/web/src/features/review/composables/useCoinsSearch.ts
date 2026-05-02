// Coin search composable — backs the /coins/search modal.
//
// Endpoint futur : GET /coins/search?country=BE&denomination=2&year=&limit=24
// (cf. docs/sources-refacto/review-queue.md §"Endpoints API attendus").
// V1 mock — génère 24 entrées par filtre.

export interface CoinSearchEntry {
  eurio_id: string
  country: string
  denomination: string
  year: number
  label: string
  canonical_thumb_url: string
  is_commemorative: boolean
}

export interface CoinSearchFilters {
  country: string | null
  denomination: string | null
  year: number | null
  limit?: number
}

// ─── Constantes UX ──────────────────────────────────────────────────────

export const EURO_COUNTRIES: { code: string; label: string; flag: string }[] = [
  { code: 'BE', label: 'Belgique', flag: '🇧🇪' },
  { code: 'DE', label: 'Allemagne', flag: '🇩🇪' },
  { code: 'FR', label: 'France', flag: '🇫🇷' },
  { code: 'IT', label: 'Italie', flag: '🇮🇹' },
  { code: 'ES', label: 'Espagne', flag: '🇪🇸' },
  { code: 'NL', label: 'Pays-Bas', flag: '🇳🇱' },
  { code: 'LU', label: 'Luxembourg', flag: '🇱🇺' },
  { code: 'IE', label: 'Irlande', flag: '🇮🇪' },
  { code: 'PT', label: 'Portugal', flag: '🇵🇹' },
  { code: 'FI', label: 'Finlande', flag: '🇫🇮' },
  { code: 'GR', label: 'Grèce', flag: '🇬🇷' },
  { code: 'AT', label: 'Autriche', flag: '🇦🇹' },
  { code: 'CY', label: 'Chypre', flag: '🇨🇾' },
  { code: 'MT', label: 'Malte', flag: '🇲🇹' },
  { code: 'SK', label: 'Slovaquie', flag: '🇸🇰' },
  { code: 'SI', label: 'Slovénie', flag: '🇸🇮' },
  { code: 'EE', label: 'Estonie', flag: '🇪🇪' },
  { code: 'LV', label: 'Lettonie', flag: '🇱🇻' },
  { code: 'LT', label: 'Lituanie', flag: '🇱🇹' },
  { code: 'HR', label: 'Croatie', flag: '🇭🇷' },
  { code: 'BG', label: 'Bulgarie', flag: '🇧🇬' },
]

export const DENOMINATIONS: { value: string; label: string }[] = [
  { value: '1c', label: '1 cent' },
  { value: '2c', label: '2 cents' },
  { value: '5c', label: '5 cents' },
  { value: '10c', label: '10 cents' },
  { value: '20c', label: '20 cents' },
  { value: '50c', label: '50 cents' },
  { value: '1eur', label: '1 €' },
  { value: '2eur', label: '2 €' },
  { value: '2eur-comm', label: '2 € commémo' },
]

export const YEAR_RANGE = { min: 1999, max: 2026 }

// ─── Mock fetcher ───────────────────────────────────────────────────────

export async function searchCoins(filters: CoinSearchFilters): Promise<CoinSearchEntry[]> {
  await new Promise((r) => setTimeout(r, 100))
  const limit = filters.limit ?? 24
  if (!filters.country) return []
  if (!filters.denomination) return []

  const results: CoinSearchEntry[] = []
  const countryMeta = EURO_COUNTRIES.find((c) => c.code === filters.country)
  if (!countryMeta) return []

  const denomMeta = DENOMINATIONS.find((d) => d.value === filters.denomination)
  if (!denomMeta) return []

  const yearsCandidate =
    filters.year !== null
      ? [filters.year]
      : range(YEAR_RANGE.min, YEAR_RANGE.max + 1).filter((y) => coinExists(filters.country!, filters.denomination!, y))

  for (const y of yearsCandidate.slice(0, limit)) {
    const isComm = filters.denomination === '2eur-comm'
    const eurio = `${filters.country.toLowerCase()}-${filters.denomination}-${y}`
    results.push({
      eurio_id: eurio,
      country: filters.country,
      denomination: filters.denomination,
      year: y,
      label: `${countryMeta.label} · ${denomMeta.label} · ${y}`,
      canonical_thumb_url: `https://placehold.co/160x160/EDEDF5/1A1B4B?text=${encodeURIComponent(eurio)}`,
      is_commemorative: isComm,
    })
  }
  return results
}

// Heuristique simple : 2€ commémo seulement à partir de 2004, autres à partir
// de l'entrée du pays dans l'eurozone.
function coinExists(country: string, denom: string, year: number): boolean {
  const entryYear: Record<string, number> = {
    BE: 1999, DE: 1999, FR: 1999, IT: 1999, ES: 1999, NL: 1999, LU: 1999,
    IE: 1999, PT: 1999, FI: 1999, GR: 2002, AT: 1999, CY: 2008, MT: 2008,
    SK: 2009, SI: 2007, EE: 2011, LV: 2014, LT: 2015, HR: 2023, BG: 2026,
  }
  const start = entryYear[country] ?? 2002
  if (year < start) return false
  if (denom === '2eur-comm' && year < 2004) return false
  return true
}

function range(start: number, end: number): number[] {
  const out: number[] = []
  for (let i = start; i < end; i++) out.push(i)
  return out
}

// ─── Fuzzy search (combobox `/`) ────────────────────────────────────────

export async function fuzzySearchCoins(query: string): Promise<CoinSearchEntry[]> {
  await new Promise((r) => setTimeout(r, 60))
  const q = query.trim().toLowerCase()
  if (q.length < 2) return []

  // Parse "BE 2 2002", "fr 50c", etc. — simple heuristique.
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
  return searchCoins({ country, denomination, year, limit: 24 })
}
