// Marketplace map composable — client for B5 API `GET /sources/ebay/marketplace-map`.
//
// Le routage discovery eBay est la source de vérité côté
// `ml/sources/ebay/marketplaces.py`. Depuis le benchmark routing
// (2026-05-21), il est **uniforme** : {EBAY_DE, EBAY_ES} pour toutes
// les origines. Le front le consomme en lecture seule pour le bandeau
// "Stratégie d'extraction" du pilote eBay. Cf. front-ux.md §"Surface 1".

import { ref } from 'vue'
import { ML_API } from '@/features/training/composables/useTrainingApi'

// ─── Types (aligned on MarketplaceMapResponse, ml/api/sources_routes.py) ──

export interface MarketplaceMapEntry {
  marketplace: string // 'EBAY_DE' | 'EBAY_ES'
  query_lang: string // langue native de la query : 'de' | 'es'
}

export interface MarketplaceMap {
  marketplaces: MarketplaceMapEntry[]
}

// ─── Helpers ──────────────────────────────────────────────────────────────

/** 'EBAY_ES' → 'ES'. Robuste à un id déjà court. */
export function mktShort(mkt: string): string {
  return mkt.startsWith('EBAY_') ? mkt.slice(5) : mkt
}

/** 'EBAY_ES' → 'es' (code ISO2 minuscule, pour le drapeau). */
export function mktIso2(mkt: string): string {
  return mktShort(mkt).toLowerCase()
}

// Drapeaux SVG (flag-icons, 4x3). Import direct des assets — URL résolue
// par Vite, pas de dépendance aux classes CSS internes de la lib. Sert
// de fond aux badges marketplace (cf. MarketplaceBadge.vue).
import fr from 'flag-icons/flags/4x3/fr.svg'
import gb from 'flag-icons/flags/4x3/gb.svg'
import de from 'flag-icons/flags/4x3/de.svg'
import it from 'flag-icons/flags/4x3/it.svg'
import es from 'flag-icons/flags/4x3/es.svg'
import nl from 'flag-icons/flags/4x3/nl.svg'
import at from 'flag-icons/flags/4x3/at.svg'
import ie from 'flag-icons/flags/4x3/ie.svg'
import be from 'flag-icons/flags/4x3/be.svg'

const FLAG_SVG: Record<string, string> = { fr, gb, de, it, es, nl, at, ie, be }

/** URL du drapeau SVG pour un marketplace, ou null si non mappé. */
export function mktFlagUrl(mkt: string): string | null {
  return FLAG_SVG[mktIso2(mkt)] ?? null
}

// Fallback prudent quand l'API ML est down — reflète le routage figé
// côté `ml/sources/ebay/marketplaces.py`.
const FALLBACK_MARKETPLACES = ['EBAY_DE', 'EBAY_ES']

/**
 * Marketplaces interrogés en discovery. Routage uniforme : la même
 * paire {EBAY_DE, EBAY_ES} quelle que soit l'origine du coin.
 */
export function discoveryMarketplaces(map: MarketplaceMap | null): string[] {
  if (!map || map.marketplaces.length === 0) return [...FALLBACK_MARKETPLACES]
  return map.marketplaces.map((m) => m.marketplace)
}

/** Nombre de search calls discovery par pièce (constant — routage uniforme). */
export function discoveryCallCount(map: MarketplaceMap | null): number {
  return discoveryMarketplaces(map).length
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
