// Marketplace map composable — client for B5 API `GET /sources/ebay/marketplace-map`.
//
// Le routage pays → marketplaces eBay est la source de vérité côté
// `ml/sources/ebay/marketplaces.py`. Le front le consomme en lecture
// seule pour (1) le bandeau "Stratégie d'extraction" du pilote eBay,
// (2) la table complète en modal. Cf. front-ux.md §"Surface 1".

import { ref } from 'vue'
import { ML_API } from '@/features/training/composables/useTrainingApi'

// ─── Types (aligned on MarketplaceMapResponse, ml/api/sources_routes.py) ──

export interface MarketplaceMapEntry {
  country: string // ISO2 ou 'eu'
  primary: string | null // 'EBAY_DE' | null si GB-only
  global_: string // toujours 'EBAY_GB' en V1
  query_lang: string
}

export interface MarketplaceMap {
  entries: MarketplaceMapEntry[]
}

// ─── Helpers ──────────────────────────────────────────────────────────────

/** 'EBAY_ES' → 'ES'. Robuste à un id déjà court. */
export function mktShort(mkt: string): string {
  return mkt.startsWith('EBAY_') ? mkt.slice(5) : mkt
}

/**
 * Marketplaces effectivement appelés en discovery pour un coin de ce pays.
 *
 * Réplique la logique de `EbayAdapter.discover` : on appelle le primary
 * natif (s'il existe et diffère de GB) PUIS toujours le global GB.
 * Pays inconnu de la map → `[global GB]` par défaut prudent.
 */
export function marketplacesForCountry(
  map: MarketplaceMap | null,
  country: string,
): string[] {
  const entry = map?.entries.find((e) => e.country === country)
  if (!entry) return ['EBAY_GB']
  if (entry.primary && entry.primary !== entry.global_) {
    return [entry.primary, entry.global_]
  }
  return [entry.global_]
}

/** Nombre de search calls discovery pour un coin de ce pays (1 ou 2). */
export function callsForCountry(map: MarketplaceMap | null, country: string): number {
  return marketplacesForCountry(map, country).length
}

/**
 * Estimation a priori du coût quota moyen (calls/eurio_id) sur un batch.
 *
 * Calcul front-only à partir du routage — pas de tracker runtime
 * (cf. front-ux.md §"Source du chiffre ~1.7"). Renvoie 0 sur batch vide.
 */
export function avgCallsForBatch(
  map: MarketplaceMap | null,
  countries: string[],
): number {
  if (countries.length === 0) return 0
  const total = countries.reduce((s, c) => s + callsForCountry(map, c), 0)
  return total / countries.length
}

// ─── Fetcher (real API, null on backend down — pas de mock) ───────────────

export function useMarketplaceMap() {
  const map = ref<MarketplaceMap | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function load() {
    loading.value = true
    error.value = null
    try {
      const resp = await fetch(`${ML_API}/sources/ebay/marketplace-map`)
      if (!resp.ok) {
        error.value = `HTTP ${resp.status}`
        return
      }
      map.value = (await resp.json()) as MarketplaceMap
    } catch {
      // Backend down — le bandeau dégrade proprement (cf. parity-rules).
      error.value = 'API ML indisponible'
    } finally {
      loading.value = false
    }
  }

  return { map, loading, error, load }
}
