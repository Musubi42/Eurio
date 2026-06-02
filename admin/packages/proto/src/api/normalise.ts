/* api/normalise.ts — RawCoin (snapshot) → Coin (surface plate typée). */

import type { Coin, RawCoin } from './types'

export function normaliseCoin(c: RawCoin): Coin {
  const cents = c.face_value_cents ?? 0
  return {
    eurioId: c.eurio_id,
    country: (c.country || '').toLowerCase(),
    countryName: c.country_name || c.country || '?',
    year: c.year ?? null,
    faceValueCents: cents,
    faceValue: cents / 100,
    isCommemorative: !!c.is_commemorative,
    collectorOnly: !!c.collector_only,
    theme: c.theme ?? null,
    designDescription: c.design_description ?? null,
    variantKind: c.variant_kind ?? null,
    canonicalEurioId: c.canonical_eurio_id ?? null,
    designGroupId: c.design_group_id ?? null,
    sharedReverseId: c.shared_reverse_id ?? null,
    mintage: c.mintage ?? c.observations?.wikipedia?.mintage_total ?? null,
    diameterMm: c.diameter_mm ?? null,
    weightG: c.weight_g ?? null,
    composition: c.composition ?? null,
    edgeDescription: c.edge_description ?? null,
    demonetized: !!c.demonetized,
    names: c.names ?? {},
    descriptions: c.descriptions ?? {},
    topics: c.topics ?? [],
    credits: c.credits ?? null,
    mintReleases: c.mint_releases ?? [],
    provenance: {
      sourcesUsed: c.provenance?.sources_used ?? [],
      lastUpdated: c.provenance?.last_updated ?? null,
    },
    raw: c,
  }
}
