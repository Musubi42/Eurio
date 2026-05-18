import { computed, ref } from 'vue'

const ML_API = 'http://127.0.0.1:8042'

export type ReviewHint = 'rebind' | 'verify_parent' | 'confirm_or_rematch_uncertain'

export interface RebindPayload {
  kind: 'rebind'
  lost_at: string
  audit_old_nid: string | null
  audit_old_catalog_name: string | null
  current_numista_id: number | string | null
}

export interface VerifyParentPayload {
  kind: 'verify_parent'
  bucket: 'B2' | 'B3'
  primary_numista_id: string | null
  member_variants: Array<{
    variant_id: string
    finish: string
    numista_id: string
    catalog_name: string
  }>
  review_reason_seed: string
}

export interface UncertainPayload {
  kind: 'confirm_or_rematch_uncertain'
  suspect_numista_id: string
  suspect_catalog_name: string | null
  current_numista_id: number | string | null
  country: string | null
  year: number | null
}

export type ReviewPayload = RebindPayload | VerifyParentPayload | UncertainPayload | Record<string, never>

export interface CoinVariantRow {
  id: string
  parent_type_id: string
  finish: string
  obverse_url: string | null
  reverse_url: string | null
  notes: string | null
}

export interface ReviewItem {
  eurio_id: string
  country: string
  year: number
  theme: string | null
  design_description: string | null
  is_commemorative: boolean
  cross_refs: Record<string, unknown>
  images: unknown
  design_group_id: string | null
  review_reason: string | null
  review_action_hint: ReviewHint
  review_payload: ReviewPayload
  variants: CoinVariantRow[]
}

export interface CatalogHit {
  numista_id: string
  name: string
  country: string | null
  country_iso2: string | null
  year: number | null
  face_value: number | null
  type: string | null
  score: number
  source: 'local' | 'numista_live'
}

export function useCoinsReview() {
  const queue = ref<ReviewItem[]>([])
  const loading = ref(false)
  const saving = ref(false)
  const error = ref<string | null>(null)
  const selectedEid = ref<string | null>(null)

  async function fetchQueue() {
    loading.value = true
    error.value = null
    try {
      const r = await fetch(`${ML_API}/coins-review/queue`)
      if (!r.ok) throw new Error(`API ${r.status}`)
      queue.value = await r.json()
      if (queue.value.length > 0 && !selectedEid.value) {
        selectedEid.value = queue.value[0].eurio_id
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  async function searchNumista(params: {
    q?: string
    country?: string | null
    year?: number | null
    includeLive?: boolean
    limit?: number
  }): Promise<CatalogHit[]> {
    const usp = new URLSearchParams()
    if (params.q) usp.set('q', params.q)
    if (params.country) usp.set('country', params.country.toLowerCase())
    if (params.year) usp.set('year', String(params.year))
    if (params.includeLive) usp.set('include_live', 'true')
    usp.set('limit', String(params.limit ?? 20))
    const r = await fetch(`${ML_API}/coins-review/search-numista?${usp}`)
    if (!r.ok) throw new Error(`search failed (${r.status})`)
    return r.json()
  }

  async function rebind(eid: string, numistaId: string, nativeUrl?: string | null) {
    saving.value = true
    try {
      const r = await fetch(`${ML_API}/coins-review/${eid}/rebind`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ numista_id: String(numistaId), native_url: nativeUrl ?? null }),
      })
      if (!r.ok) throw new Error(await r.text())
      removeFromQueue(eid)
      return await r.json()
    } finally {
      saving.value = false
    }
  }

  async function noCoverage(eid: string, note?: string) {
    saving.value = true
    try {
      const r = await fetch(`${ML_API}/coins-review/${eid}/no-coverage`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note: note ?? null }),
      })
      if (!r.ok) throw new Error(await r.text())
      removeFromQueue(eid)
      return await r.json()
    } finally {
      saving.value = false
    }
  }

  async function deleteRedirect(eid: string, targetEid: string) {
    saving.value = true
    try {
      const r = await fetch(`${ML_API}/coins-review/${eid}/delete-redirect`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_eurio_id: targetEid, confirm: true }),
      })
      if (!r.ok) throw new Error(await r.text())
      removeFromQueue(eid)
      return await r.json()
    } finally {
      saving.value = false
    }
  }

  function removeFromQueue(eid: string) {
    const idx = queue.value.findIndex(i => i.eurio_id === eid)
    if (idx < 0) return
    const wasSelected = selectedEid.value === eid
    queue.value.splice(idx, 1)
    if (wasSelected) {
      const next = queue.value[idx] ?? queue.value[idx - 1] ?? null
      selectedEid.value = next?.eurio_id ?? null
    }
  }

  const grouped = computed(() => {
    const order: ReviewHint[] = ['rebind', 'verify_parent', 'confirm_or_rematch_uncertain']
    const buckets = new Map<ReviewHint, ReviewItem[]>(order.map(h => [h, []]))
    for (const it of queue.value) {
      buckets.get(it.review_action_hint)?.push(it)
    }
    return order.map(hint => ({ hint, items: buckets.get(hint) ?? [] }))
  })

  const flatOrder = computed<ReviewItem[]>(() =>
    grouped.value.flatMap(g => g.items)
  )

  const selected = computed<ReviewItem | null>(
    () => flatOrder.value.find(i => i.eurio_id === selectedEid.value) ?? null
  )

  function select(eid: string) {
    selectedEid.value = eid
  }

  function selectRelative(delta: number) {
    const list = flatOrder.value
    if (list.length === 0) {
      selectedEid.value = null
      return
    }
    const idx = list.findIndex(i => i.eurio_id === selectedEid.value)
    const nextIdx = Math.max(0, Math.min(list.length - 1, (idx < 0 ? 0 : idx) + delta))
    selectedEid.value = list[nextIdx].eurio_id
  }

  const stats = computed(() => ({
    total: queue.value.length,
    rebind: grouped.value[0].items.length,
    verify_parent: grouped.value[1].items.length,
    confirm_or_rematch_uncertain: grouped.value[2].items.length,
  }))

  return {
    queue, loading, saving, error,
    stats, grouped, flatOrder, selected,
    fetchQueue, searchNumista, rebind, noCoverage, deleteRedirect,
    select, selectRelative,
  }
}

// ─── Helpers ───────────────────────────────────────────────────────────────

export function countryFlag(code: string | null | undefined): string {
  if (!code) return ''
  const cc = code.toUpperCase()
  // Special pseudo-country: EU joint-issue (use generic ⭕)
  if (cc === 'EU') return '🇪🇺'
  if (cc.length !== 2) return ''
  return cc.replace(/./g, c => String.fromCodePoint(c.charCodeAt(0) + 127397))
}

export const HINT_LABEL: Record<ReviewHint, string> = {
  rebind: 'Rebind',
  verify_parent: 'Vérifier parent',
  confirm_or_rematch_uncertain: 'Confirmer / rematch',
}

export const HINT_TAGLINE: Record<ReviewHint, string> = {
  rebind: 'Numista nid manquant après 3b — retrouver le bon match',
  verify_parent: 'Parent abstrait créé en 3d — confirmer les métadonnées',
  confirm_or_rematch_uncertain: 'Audit a flaggé un overlap thématique — décider',
}
