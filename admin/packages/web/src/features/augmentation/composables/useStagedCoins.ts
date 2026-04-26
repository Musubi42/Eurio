// Reads the `eurio_ids` query param from the route and hydrates the
// corresponding Coin rows from Supabase. Keeps everything reactive — if the
// user navigates with a different set of ids, the list updates.

import { supabase } from '@/shared/supabase/client'
import type { Coin } from '@/shared/supabase/types'
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

export function useStagedCoins(maxCoins: number = 20) {
  const route = useRoute()
  const coins = ref<Coin[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const activeIndex = ref(0)

  const requestedIds = computed<string[]>(() => {
    const raw = route.query.eurio_ids
    if (typeof raw !== 'string' || !raw) return []
    return raw
      .split(',')
      .map(s => s.trim())
      .filter(Boolean)
      .slice(0, maxCoins)
  })

  const active = computed<Coin | null>(() => coins.value[activeIndex.value] ?? null)

  async function load() {
    const ids = requestedIds.value
    if (ids.length === 0) {
      coins.value = []
      activeIndex.value = 0
      return
    }
    loading.value = true
    error.value = null
    try {
      const { data, error: err } = await supabase
        .from('coins')
        .select('*')
        .in('eurio_id', ids)
      if (err) throw err
      // Preserve the order of the query param.
      const byId = new Map((data as Coin[]).map(c => [c.eurio_id, c]))
      coins.value = ids
        .map(id => byId.get(id))
        .filter((c): c is Coin => c != null)
      if (activeIndex.value >= coins.value.length) {
        activeIndex.value = 0
      }
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Failed to load coins'
      coins.value = []
    } finally {
      loading.value = false
    }
  }

  function setActive(index: number) {
    if (index >= 0 && index < coins.value.length) {
      activeIndex.value = index
    }
  }

  // Re-load whenever the query param changes (including first mount).
  watch(requestedIds, load, { immediate: true })

  return { coins, active, activeIndex, setActive, loading, error, requestedIds, load }
}
