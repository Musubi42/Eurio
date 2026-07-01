// Vue Query composables for the "rarely changes" coin lookups used by
// CoinsPage filters. Centralised so CoinDetail / CohortNew / future pages
// share the same cache + invalidation semantics.
//
// Cache strategy: defaultOptions in shared/query/client.ts already give us
// staleTime 5min + gcTime 24h + IDB persistence. These hooks just declare
// the query keys + fetchers; mutations elsewhere call queryClient.
// invalidateQueries on the same key to refresh.
//
// P.8b — refactor pour utiliser l'API ml/ FastAPI (doctrine SQLite-only).
// Plus de read direct Supabase. Backend : ml/api/coins_routes.py.

import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { fetchZoneMap } from '@/features/confusion/composables/useConfusionMap'
import {
  fetchSourceCounts,
  fetchTrainedEurioIds,
  patchCoin,
  type SourceKey,
} from '@/features/coins/composables/useCoinsApi'
import type { ConfusionZone } from '@/shared/types/domain'

export const COIN_LOOKUP_KEYS = {
  trained: ['coins', 'lookups', 'trained'] as const,
  zones: ['coins', 'lookups', 'zones'] as const,
  sourceCounts: ['coins', 'lookups', 'source-counts'] as const,
}

// ─── Trained eurio_ids ──────────────────────────────────────────────────

export function useTrainedEurioIds() {
  return useQuery({
    queryKey: COIN_LOOKUP_KEYS.trained,
    queryFn: async (): Promise<Set<string>> => {
      const ids = await fetchTrainedEurioIds()
      return new Set(ids)
    },
  })
}

// ─── Confusion-map zones ────────────────────────────────────────────────

export type ZoneEntry = { zone: ConfusionZone; nearest_similarity: number }
export type ZoneMap = Map<string, ZoneEntry>

export function useConfusionZoneMap() {
  return useQuery<ZoneMap>({
    queryKey: COIN_LOOKUP_KEYS.zones,
    queryFn: () => fetchZoneMap(),
  })
}

// ─── Source counts (per-source row counts shown in chips) ───────────────

export type { SourceKey }

export function useSourceCounts() {
  return useQuery<Partial<Record<SourceKey, number>>>({
    queryKey: COIN_LOOKUP_KEYS.sourceCounts,
    queryFn: () => fetchSourceCounts(),
    staleTime: 30 * 60 * 1000, // 30 min — source counts move slowly
  })
}

// ─── Mutation helpers ───────────────────────────────────────────────────

/**
 * Flip a boolean column on `coins` for one row. Uses the FastAPI
 * `PATCH /coins/{eurio_id}` endpoint backed by eurio.db.
 */
export async function flipCoinFlag(
  eurioId: string,
  column: 'personal_owned' | 'lent_to_me',
  next: boolean,
): Promise<void> {
  await patchCoin(eurioId, { [column]: next })
}

export function useInvalidateCoinLookups() {
  const qc = useQueryClient()
  return {
    invalidateTrained: () => qc.invalidateQueries({ queryKey: COIN_LOOKUP_KEYS.trained }),
    invalidateZones: () => qc.invalidateQueries({ queryKey: COIN_LOOKUP_KEYS.zones }),
    invalidateSourceCounts: () => qc.invalidateQueries({ queryKey: COIN_LOOKUP_KEYS.sourceCounts }),
  }
}
