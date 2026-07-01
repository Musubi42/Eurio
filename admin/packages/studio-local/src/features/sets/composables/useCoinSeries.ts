import { onMounted, ref } from 'vue'
import { eurioApi } from '@/shared/api/eurio-api'
import type { CoinSeries } from '@/shared/types/domain'

/**
 * Fetch et cache les 32 entrées coin_series (picker série).
 * Une seule query par session — elles sont stables.
 *
 * Source : eurio-api `GET /coin-series` (canonique SQLite, D2
 * data-layer-unification) — déjà trié server-side par (country,
 * minting_started_at). Remplace le dernier `supabase.from()` runtime.
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
    try {
      cache.value = await eurioApi.get<CoinSeries[]>('/coin-series')
      series.value = cache.value
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  onMounted(fetchSeries)

  return { series, loading, error }
}
