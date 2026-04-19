import { supabase } from '@/shared/supabase/client'
import type { CoinSeries } from '@/shared/supabase/types'
import { onMounted, ref } from 'vue'

/**
 * Fetch et cache les 32 entrées coin_series (picker série).
 * Une seule query par session — elles sont stables.
 */
const cache = ref<CoinSeries[] | null>(null)

export function useCoinSeries() {
  const series = ref<CoinSeries[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchSeries() {
    if (cache.value) {
      series.value = cache.value
      return
    }
    loading.value = true
    const { data, error: err } = await supabase
      .from('coin_series')
      .select('*')
      .order('country')
      .order('minting_started_at')

    loading.value = false
    if (err) { error.value = err.message; return }

    cache.value = (data ?? []) as CoinSeries[]
    series.value = cache.value
  }

  onMounted(fetchSeries)

  return { series, loading, error }
}
