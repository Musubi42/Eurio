// Couche vue-query du badge de sync (poll conditionnel + trigger manuel).
// Patron : useTrainingScanStatusQuery / useStartTrainingScanMutation (lab).

import { fetchSyncStatus, triggerSync } from '@/shared/api/sync-api'
import { useCapabilities } from '@/stores/capabilities'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed } from 'vue'

export const SYNC_KEYS = {
  status: ['sync', 'status'] as const,
}

export function useSyncStatusQuery() {
  const caps = useCapabilities()
  return useQuery({
    queryKey: SYNC_KEYS.status,
    queryFn: fetchSyncStatus,
    enabled: computed(() => caps.hasLocalMlApi),
    // 5 s pendant une sync (l'utilisateur regarde le badge tourner), 30 s en
    // rythme de croisière — le statut ne bouge qu'au rythme du debounce.
    refetchInterval: (query) =>
      query.state.data?.state === 'syncing' ? 5_000 : 30_000,
    staleTime: 0,
  })
}

export function useTriggerSyncMutation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: triggerSync,
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: SYNC_KEYS.status })
    },
  })
}
