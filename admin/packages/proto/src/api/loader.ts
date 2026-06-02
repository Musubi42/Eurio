/* api/loader.ts — LE SEUL POINT BAS-NIVEAU de chargement des données.
 *
 * ⚠️ Point de contact unique avec le chantier « eurio.db source unique ».
 * L'autre session repointe ICI (et seulement ici) la provenance du snapshot.
 * Aucune scène ni aucun store ne charge de données ailleurs.
 *
 * Deux modes via VITE_DATA_MODE :
 *   - 'fixtures' (défaut) → fetch data/app_core.json packagé (public/).
 *   - 'live'              → fetch Supabase (PostgREST). Stub tant que la
 *                           read-surface live n'est pas branchée.
 */

import type { Snapshot } from './types'

const MODE: 'fixtures' | 'live' = import.meta.env.VITE_DATA_MODE ?? 'fixtures'

// Storage public Supabase (avers). Public par design — pas de clé requise.
const SUPABASE_URL = 'https://ettxkixkxrzchbnohgfm.supabase.co'
const STORAGE_PUBLIC = `${SUPABASE_URL}/storage/v1/object/public`

/** URL publique de l'avers (face nationale) webp d'une pièce dans Storage. */
export function obverseUrl(eurioId: string): string {
  return `${STORAGE_PUBLIC}/coin-images/${eurioId}/obverse.webp`
}

let _cache: Promise<Snapshot> | null = null

/** Charge le snapshot brut (une fois, mémoïsé). */
export function loadSnapshot(): Promise<Snapshot> {
  if (_cache) return _cache
  _cache = MODE === 'live' ? loadLive() : loadFixtures()
  return _cache
}

async function loadFixtures(): Promise<Snapshot> {
  const url = `${import.meta.env.BASE_URL}data/app_core.json`
  const res = await fetch(url, { cache: 'force-cache' })
  if (!res.ok) {
    throw new Error(
      `[loader] app_core.json introuvable (${res.status}). ` +
        'Régénère-le via `go-task ml:build-app-core`.',
    )
  }
  return (await res.json()) as Snapshot
}

async function loadLive(): Promise<Snapshot> {
  // Branchement de la read-surface Supabase au passage du flag (cf. Chunk F).
  throw new Error('[loader] mode "live" pas encore branché (cf. Chunk F).')
}
