import { eurioApi } from '@/shared/api/eurio-api'
import type { Coin, SetCriteria } from '@/shared/types/domain'
import { useDebounceFn } from '@vueuse/core'
import { ref, watch, type Ref } from 'vue'

/**
 * Construit une query eurio-api depuis un SetCriteria et retourne
 * { count, samples, loading, error } réactifs.
 *
 * Phase 2a data-layer-unification : porté de Supabase PostgREST →
 * eurio-api ``/coins`` qui supporte désormais year/series_id/variant_kind/
 * min_mintage/max_mintage en plus de country/fv/commemo.
 *
 * - Pour les critères simples, on délègue les filtres à eurio-api.
 * - Pour `distinct_by`, on fait le dédoublonnage côté client après fetch.
 *
 * Note : `issue_type` Supabase ↔ `variant_kind` SQLite (renommage).
 * `is_withdrawn` n'existe pas en SQLite — filtre ignoré.
 */
const MAX_FETCH = 1000

export function useCriteriaPreview(criteria: Ref<SetCriteria | null>) {
  const count = ref<number>(0)
  const samples = ref<Coin[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const isEmpty = ref(true)

  async function runQuery() {
    const c = criteria.value
    if (!c || Object.keys(c).length === 0) {
      count.value = 0
      samples.value = []
      isEmpty.value = true
      return
    }
    isEmpty.value = false
    loading.value = true
    error.value = null

    const params = new URLSearchParams()
    params.set('limit', String(c.distinct_by ? MAX_FETCH : 24))

    // country
    if (c.country) {
      const countries = (Array.isArray(c.country) ? c.country : [c.country])
        .map(s => s.toUpperCase())
      if (countries.length) params.set('country', countries.join(','))
    }

    // issue_type → variant_kind (renommage Supabase → SQLite)
    if (c.issue_type) {
      const types = Array.isArray(c.issue_type) ? c.issue_type : [c.issue_type]
      if (types.length) params.set('variant_kind', types.join(','))
    }

    // year
    if (typeof c.year === 'number') {
      params.set('year', String(c.year))
    } else if (c.year === 'current') {
      params.set('year', String(new Date().getFullYear()))
    }

    // denomination (face_value) — un seul supporté pour l'instant côté API
    if (c.denomination && c.denomination.length > 0) {
      // L'endpoint /coins accepte un seul fv. Pour multi-fv, post-filter client-side.
      if (c.denomination.length === 1) {
        params.set('fv', String(c.denomination[0]))
      }
    }

    // series_id
    if (c.series_id) {
      params.set('series_id', c.series_id)
    }

    // is_withdrawn : absent côté SQLite — filtre ignoré (à porter si besoin)

    // mintage bounds
    if (c.min_mintage !== undefined) params.set('min_mintage', String(c.min_mintage))
    if (c.max_mintage !== undefined) params.set('max_mintage', String(c.max_mintage))

    let resp: { items: Coin[], total: number }
    try {
      resp = await eurioApi.get<{ items: Coin[], total: number }>(
        `/coins?${params.toString()}`,
      )
    } catch (e) {
      loading.value = false
      error.value = e instanceof Error ? e.message : String(e)
      return
    }
    loading.value = false

    let rows = resp.items ?? []

    // Post-filter denomination multi-valeurs si pas géré côté API
    if (c.denomination && c.denomination.length > 1) {
      const set = new Set(c.denomination)
      rows = rows.filter(r => set.has(r.face_value))
    }

    if (c.distinct_by === 'country') {
      // Dedup côté client
      const seen = new Set<string>()
      const deduped: Coin[] = []
      for (const row of rows) {
        if (!seen.has(row.country)) {
          seen.add(row.country)
          deduped.push(row)
        }
      }
      count.value = deduped.length
      samples.value = deduped.slice(0, 24)
    } else {
      count.value = resp.total ?? rows.length
      samples.value = rows.slice(0, 24)
    }
  }

  const debouncedRun = useDebounceFn(runQuery, 300)

  watch(criteria, debouncedRun, { deep: true, immediate: true })

  return { count, samples, loading, error, isEmpty, refresh: runQuery }
}
