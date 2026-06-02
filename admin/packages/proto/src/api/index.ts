/* api/index.ts — LE CONTRAT DE DONNÉES (surface publique).
 *
 * Tout l'accès données du proto passe ICI. Les vues/stores n'importent jamais
 * loader.ts, le snapshot brut, ni un JSON directement. Une seule couture.
 *
 * Cycle de vie : `await initApi()` une fois au boot (main.ts), puis les getters
 * synchrones. Déterministe tant qu'on est en fixtures.
 */

import { SET_DETAILS, SET_PREVIEWS } from './fixtures/sets'
import { EUROZONE_PROGRESS, isComplete } from './fixtures/eurozone'
import { COUNTRY_PLANCHES } from './fixtures/country-planches'
import { loadSnapshot, obverseUrl } from './loader'
import { isParity } from './parity'
import { deriveMarket, deriveReveal } from './market'
import { normaliseCoin } from './normalise'
import { deriveRecit } from './recit'
import { coinSvg } from './svg'
import { fold } from './util'
import type {
  Coin,
  Coin3DAssets,
  CoinFilter,
  CountryPlanche,
  CountryProgress,
  Market,
  Recit,
  Reveal,
  SetDetail,
  SetPreview,
} from './types'

// ───────── État interne (rempli par initApi) ─────────

let _ready = false
let _all: Coin[] = []
const _byId = new Map<string, Coin>()
const _sharedReverse = new Map<string, string>() // id → asset_name
const _withTextures: Coin[] = [] // pièces ayant un avers+revers (pour le 3D/scan)

export async function initApi(): Promise<void> {
  if (_ready) return
  const snap = await loadSnapshot()
  _all = snap.coins.map(normaliseCoin)
  _byId.clear()
  for (const c of _all) _byId.set(c.eurioId, c)
  _sharedReverse.clear()
  for (const sr of snap.shared_reverse ?? []) _sharedReverse.set(sr.id, sr.asset_name)
  _withTextures.length = 0
  for (const c of _all) {
    if (c.sharedReverseId && _sharedReverse.has(c.sharedReverseId)) _withTextures.push(c)
  }
  _ready = true
}

export function isReady(): boolean {
  return _ready
}

// ───────── Pièces ─────────

export function getCoin(eurioId: string): Coin | null {
  return _byId.get(eurioId) ?? null
}

export function allCoins(): Coin[] {
  return _all.slice()
}

export function allCountries(): string[] {
  return [...new Set(_all.map((c) => c.country).filter(Boolean))].sort()
}

export function getCoinsByCountry(iso: string): Coin[] {
  const c = iso.toLowerCase()
  return _all.filter((coin) => coin.country === c)
}

export function filterCoins(criteria: CoinFilter = {}): Coin[] {
  return _all.filter((c) => {
    if (criteria.country && c.country !== criteria.country.toLowerCase()) return false
    if (criteria.year && c.year !== criteria.year) return false
    if (criteria.faceValueCents != null && c.faceValueCents !== criteria.faceValueCents) return false
    if (criteria.isCommemorative != null && c.isCommemorative !== criteria.isCommemorative) return false
    return true
  })
}

export function searchCoins(query: string): Coin[] {
  if (!query) return []
  const q = fold(query)
  return _all.filter((c) => fold(`${c.countryName} ${c.theme ?? ''}`).includes(q))
}

/** Membres d'un même design_group (émission commune zone euro). */
export function getDesignGroupMembers(eurioId: string): Coin[] {
  const coin = _byId.get(eurioId)
  if (!coin?.designGroupId) return []
  return _all.filter((c) => c.designGroupId === coin.designGroupId)
}

// ───────── Dérivés (marché, récit, reveal) ─────────

export function getMarket(eurioId: string): Market | null {
  const coin = _byId.get(eurioId)
  return coin ? deriveMarket(coin) : null
}

export function getRecit(eurioId: string): Recit | null {
  const coin = _byId.get(eurioId)
  return coin ? deriveRecit(coin) : null
}

export function getReveal(eurioId: string): Reveal | null {
  const coin = _byId.get(eurioId)
  return coin ? deriveReveal(coin) : null
}

// ───────── Assets 3D ─────────

export function getCoin3DAssets(eurioId: string): Coin3DAssets | null {
  const coin = _byId.get(eurioId)
  if (!coin?.sharedReverseId) return null
  const asset = _sharedReverse.get(coin.sharedReverseId)
  if (!asset) return null
  return {
    obverse: coin.obverseImageUrl ?? obverseUrl(coin.eurioId),
    reverse: `data/shared_reverse/${asset}`,
    edge: 'procedural',
    uv: { repeat: 1, offset: 0 },
  }
}

// ───────── Progression pays (fixture démo) ─────────

export function getCountryProgress(): CountryProgress[] {
  return EUROZONE_PROGRESS.map((c) => ({ ...c }))
}

export function isCountryComplete(c: CountryProgress): boolean {
  return isComplete(c)
}

/** Planche complète d'un pays (fixture démo). Fallback FR. */
export function getCountryPlanche(iso: string): CountryPlanche {
  return COUNTRY_PLANCHES[iso.toUpperCase()] ?? COUNTRY_PLANCHES.FR
}

// ───────── Sets (fixture démo, cf. fixtures/sets.ts) ─────────

export function getSets(): SetPreview[] {
  return SET_PREVIEWS.slice()
}

export function getSet(setId: string): SetDetail | null {
  return SET_DETAILS[setId] ?? null
}

// ───────── Faux-scan ─────────
// La couture : renvoie l'eurio_id d'une pièce qui a des textures (pour que le
// reveal 3D fonctionne). Déterministe par seed pour les replays scriptés.

export function simulateScan(seed?: number): string {
  const pool = _withTextures.length ? _withTextures : _all
  if (!pool.length) throw new Error('[api] aucune pièce dans le snapshot')
  const idx = seed != null ? seed % pool.length : Math.floor(Math.random() * pool.length)
  return pool[idx].eurioId
}

// ───────── Helpers ─────────

export { coinSvg }

/**
 * URL de l'avers (face nationale) webp d'une pièce. Préfère l'URL portée par le
 * contrat (`coin.obverseImageUrl`, peuplée en mode live depuis
 * `coin_image.storage_path`) ; à défaut (fixtures), retombe sur la convention de
 * chemin Storage. Seule couture pour l'avers → pas de layout Storage codé en dur
 * côté vues. Le revers (côté commun, packagé) passe par getCoin3DAssets.
 *
 * En parité (capture hermétique), on NE retombe PAS sur l'URL Storage (réseau) :
 * absence d'avers local → null → CoinImage bascule sur le fallback SVG.
 */
export function coinObverseUrl(coin: Coin): string | null {
  if (coin.obverseImageUrl) return coin.obverseImageUrl
  return isParity() ? null : obverseUrl(coin.eurioId)
}

// Ré-export des types (le contrat) pour les vues/stores.
export type * from './types'
