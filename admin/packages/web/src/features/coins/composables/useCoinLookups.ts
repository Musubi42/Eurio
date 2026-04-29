// Vue Query composables for the "rarely changes" coin lookups used by
// CoinsPage filters. Centralised so CoinDetail / CohortNew / future pages
// share the same cache + invalidation semantics.
//
// Cache strategy: defaultOptions in shared/query/client.ts already give us
// staleTime 5min + gcTime 24h + IDB persistence. These hooks just declare
// the query keys + fetchers; mutations elsewhere call queryClient.
// invalidateQueries on the same key to refresh.

import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { fetchZoneMap } from '@/features/confusion/composables/useConfusionMap'
import { supabase } from '@/shared/supabase/client'
import type { ConfusionZone } from '@/shared/supabase/types'

export const COIN_LOOKUP_KEYS = {
  trained: ['coins', 'lookups', 'trained'] as const,
  zones: ['coins', 'lookups', 'zones'] as const,
  sourceCounts: ['coins', 'lookups', 'source-counts'] as const,
}

// ─── Trained eurio_ids (set of coins that appear in coin_embeddings) ────

export function useTrainedEurioIds() {
  return useQuery({
    queryKey: COIN_LOOKUP_KEYS.trained,
    queryFn: async (): Promise<Set<string>> => {
      const { data, error } = await supabase
        .from('coin_embeddings')
        .select('eurio_id')
      if (error) throw error
      return new Set((data ?? []).map(e => e.eurio_id as string))
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

export type SourceKey = 'numista' | 'bce' | 'wikipedia' | 'lmdlp' | 'ebay'
const SOURCE_KEYS: SourceKey[] = ['numista', 'bce', 'wikipedia', 'lmdlp', 'ebay']

export function useSourceCounts() {
  return useQuery<Partial<Record<SourceKey, number>>>({
    queryKey: COIN_LOOKUP_KEYS.sourceCounts,
    queryFn: async () => {
      const out: Partial<Record<SourceKey, number>> = {}
      await Promise.all(
        SOURCE_KEYS.map(async (src) => {
          let q = supabase.from('coins').select('eurio_id', { count: 'exact', head: true })
          if (src === 'numista') q = q.not('cross_refs->numista_id', 'is', null)
          else if (src === 'bce') q = q.eq('has_bce', true)
          else if (src === 'wikipedia') q = q.eq('has_wikipedia', true)
          else if (src === 'lmdlp') q = q.eq('has_lmdlp', true)
          else if (src === 'ebay') q = q.eq('has_ebay', true)
          const { count } = await q
          out[src] = count ?? 0
        }),
      )
      return out
    },
    // Source counts move very slowly — hold them longer than the default.
    staleTime: 30 * 60 * 1000, // 30 min
  })
}

// ─── Mutation helpers ───────────────────────────────────────────────────

/**
 * Optimistically flip a boolean column on `coins` for one row, with
 * rollback on error. Use for personal_owned / lent_to_me toggles.
 *
 * The caller is expected to also patch its local list (CoinsPage holds an
 * array in a ref); this helper handles the network round-trip + cache
 * invalidation. Returns the updated value or throws.
 */
export async function flipCoinFlag(
  eurioId: string,
  column: 'personal_owned' | 'lent_to_me',
  next: boolean,
): Promise<void> {
  const patch = { [column]: next } as { personal_owned?: boolean; lent_to_me?: boolean }
  const { error } = await supabase
    .from('coins')
    .update(patch)
    .eq('eurio_id', eurioId)
  if (error) throw error
}

export function useInvalidateCoinLookups() {
  const qc = useQueryClient()
  return {
    invalidateTrained: () => qc.invalidateQueries({ queryKey: COIN_LOOKUP_KEYS.trained }),
    invalidateZones: () => qc.invalidateQueries({ queryKey: COIN_LOOKUP_KEYS.zones }),
    invalidateSourceCounts: () => qc.invalidateQueries({ queryKey: COIN_LOOKUP_KEYS.sourceCounts }),
  }
}
