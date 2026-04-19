import { supabase } from '@/shared/supabase/client'
import type { Coin, SetCriteria } from '@/shared/supabase/types'
import { useDebounceFn } from '@vueuse/core'
import { ref, watch, type Ref } from 'vue'

/**
 * Construit une query Supabase depuis un SetCriteria et retourne
 * { count, samples, loading, error } réactifs.
 *
 * - Pour les critères simples (country, issue_type, year, denomination, series_id,
 *   is_withdrawn, min/max_mintage), on délègue à PostgREST.
 * - Pour `distinct_by`, on fait le dédoublonnage côté client après fetch (limite 1000).
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

    let q = supabase
      .from('coins')
      .select('*', { count: c.distinct_by ? undefined : 'exact' })
      .limit(c.distinct_by ? MAX_FETCH : 24)

    // country
    if (c.country) {
      const countries = (Array.isArray(c.country) ? c.country : [c.country])
        .map(s => s.toUpperCase())
      q = countries.length === 1 ? q.eq('country', countries[0]) : q.in('country', countries)
    }

    // issue_type
    if (c.issue_type) {
      const types = Array.isArray(c.issue_type) ? c.issue_type : [c.issue_type]
      q = types.length === 1 ? q.eq('issue_type', types[0]) : q.in('issue_type', types)
    }

    // year
    if (typeof c.year === 'number') {
      q = q.eq('year', c.year)
    } else if (c.year === 'current') {
      q = q.eq('year', new Date().getFullYear())
    }

    // denomination
    if (c.denomination && c.denomination.length > 0) {
      q = c.denomination.length === 1
        ? q.eq('face_value', c.denomination[0])
        : q.in('face_value', c.denomination)
    }

    // series_id
    if (c.series_id) {
      q = q.eq('series_id', c.series_id)
    }

    // is_withdrawn
    if (c.is_withdrawn !== undefined) {
      q = q.eq('is_withdrawn', c.is_withdrawn)
    }

    // mintage bounds
    if (c.min_mintage !== undefined) q = q.gte('mintage', c.min_mintage)
    if (c.max_mintage !== undefined) q = q.lte('mintage', c.max_mintage)

    const { data, error: err, count: cnt } = await q

    loading.value = false
    if (err) { error.value = err.message; return }

    const rows = (data ?? []) as Coin[]

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
      count.value = cnt ?? rows.length
      samples.value = rows.slice(0, 24)
    }
  }

  const debouncedRun = useDebounceFn(runQuery, 300)

  watch(criteria, debouncedRun, { deep: true, immediate: true })

  return { count, samples, loading, error, isEmpty, refresh: runQuery }
}
