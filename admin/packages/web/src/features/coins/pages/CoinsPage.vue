<script setup lang="ts">
import { fetchZoneMap } from '@/features/confusion/composables/useConfusionMap'
import { zoneStyle } from '@/features/confusion/composables/useConfusionZone'
import { supabase } from '@/shared/supabase/client'
import type { Coin, ConfusionZone, IssueType } from '@/shared/supabase/types'
import { firstImageUrl } from '@/shared/utils/coin-images'
import { useDebounceFn } from '@vueuse/core'
import { Brain, Check, Copy, FlaskConical, ImageOff, Play, Search, Sparkles, Wallet } from 'lucide-vue-next'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const coins = ref<Coin[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const total = ref(0)
const offset = ref(0)
const PAGE = 60

// Filters — initialized from URL query params so browser back/forward restores state
const query = ref((route.query.q as string) || '')

// Multi-country filter. Backwards-compatible with the legacy single ?country=FR
// param: a single value seeds the Set just like a comma-separated ?countries=FR,DE.
function parseCountries(): Set<string> {
  const raw = (route.query.countries as string) || (route.query.country as string) || ''
  return new Set(raw.split(',').map(s => s.trim()).filter(Boolean))
}
const filterCountries = ref<Set<string>>(parseCountries())

const filterFaceValue = ref<number | null>(route.query.fv ? Number(route.query.fv) : null)
const filterCommemo = ref<boolean | null>(
  route.query.commemo === 'true' ? true : route.query.commemo === 'false' ? false : null,
)
const filterNumista = ref<'with' | 'without' | null>(
  (route.query.numista as 'with' | 'without') || null,
)
const filterImages = ref<'with' | 'without' | null>(
  (route.query.images as 'with' | 'without') || null,
)
const filterZone = ref<ConfusionZone | 'unmapped' | null>(
  (route.query.zone as ConfusionZone | 'unmapped') || null,
)
const filterTrained = ref<'trained' | 'not-trained' | null>(
  (route.query.trained as 'trained' | 'not-trained') || null,
)
// Personal-collection filter (admin's owned-coins flag, see migration
// 20260428_coins_personal_owned). Mirrors the trained chip pattern.
const filterPersonal = ref<'owned' | 'not-owned' | null>(
  (route.query.personal as 'owned' | 'not-owned') || null,
)

// Multi-source filter. Cumulative AND. Backed by pre-computed boolean columns
// on `coins` (has_bce/has_wikipedia/has_lmdlp/has_ebay) maintained by Postgres
// triggers, plus cross_refs->numista_id for the numista source.
type SourceKey = 'numista' | 'bce' | 'wikipedia' | 'lmdlp' | 'ebay'
const SOURCE_KEYS: SourceKey[] = ['numista', 'bce', 'wikipedia', 'lmdlp', 'ebay']
const filterSources = ref<Set<SourceKey>>(
  new Set(((route.query.sources as string) || '').split(',').filter(Boolean) as SourceKey[]),
)

const COUNTRIES = [
  'AD', 'AT', 'BE', 'BG', 'CY', 'DE', 'EE', 'ES', 'FI', 'FR',
  'GR', 'HR', 'IE', 'IT', 'LT', 'LU', 'LV', 'MC', 'MT', 'NL',
  'PT', 'SI', 'SK', 'SM', 'VA',
]

const DENOMINATIONS = [0.01, 0.02, 0.05, 0.10, 0.20, 0.50, 1, 2]

const issueLabel: Record<IssueType, string> = {
  'circulation':       'Circulation',
  'commemo-national':  'Commémo nationale',
  'commemo-common':    'Commémo commune',
  'starter-kit':       'Starter kit',
  'bu-set':            'BU set',
  'proof':             'Proof',
}

async function fetchCoins(search = '', append = false) {
  loading.value = true
  error.value = null

  let q = supabase
    .from('coins')
    .select('*', { count: 'exact' })

  if (search.trim()) {
    const s = search.trim()
    const clauses = [
      `eurio_id.ilike.%${s}%`,
      `theme.ilike.%${s}%`,
      `country.ilike.${s}`,
    ]
    // Exact match on numista_id when the query is purely numeric.
    if (/^\d+$/.test(s)) {
      clauses.push(`cross_refs->>numista_id.eq.${s}`)
    }
    q = q.or(clauses.join(','))
  }

  // Apply filters
  if (filterCountries.value.size > 0) {
    q = q.in('country', [...filterCountries.value])
  }
  if (filterFaceValue.value != null) q = q.eq('face_value', filterFaceValue.value)
  if (filterCommemo.value != null) q = q.eq('is_commemorative', filterCommemo.value)
  if (filterNumista.value === 'with') q = q.not('cross_refs->numista_id', 'is', null)
  if (filterNumista.value === 'without') q = q.is('cross_refs->numista_id', null)
  if (filterImages.value === 'with') q = q.neq('images', '[]').not('images', 'is', null)
  if (filterImages.value === 'without') q = q.or('images.eq.[],images.is.null')

  // Multi-source filter — cumulative AND on pre-computed flags.
  if (filterSources.value.has('numista')) q = q.not('cross_refs->numista_id', 'is', null)
  if (filterSources.value.has('bce'))       q = q.eq('has_bce', true)
  if (filterSources.value.has('wikipedia')) q = q.eq('has_wikipedia', true)
  if (filterSources.value.has('lmdlp'))     q = q.eq('has_lmdlp', true)
  if (filterSources.value.has('ebay'))      q = q.eq('has_ebay', true)

  // Personal-collection filter — flat boolean column on `coins`.
  if (filterPersonal.value === 'owned')     q = q.eq('personal_owned', true)
  if (filterPersonal.value === 'not-owned') q = q.eq('personal_owned', false)

  // Training filter — applies trainedEurioIds set fetched from coin_embeddings.
  if (filterTrained.value === 'trained') {
    const ids = [...trainedEurioIds.value]
    if (ids.length === 0) {
      coins.value = append ? coins.value : []
      total.value = append ? total.value : 0
      loading.value = false
      return
    }
    q = q.in('eurio_id', ids)
  } else if (filterTrained.value === 'not-trained') {
    const ids = [...trainedEurioIds.value]
    if (ids.length > 0 && ids.length < 1000) {
      q = q.not('eurio_id', 'in', `(${ids.map(id => `"${id}"`).join(',')})`)
    }
  }

  // Zone filter — uses pre-fetched confusionZones map and restricts via .in()/.not.in()
  if (filterZone.value) {
    const mapped = [...confusionZones.value.keys()]
    if (filterZone.value === 'unmapped') {
      // Coins NOT in confusion map. Avoid huge IN() lists: fallback to no-op if >1k mapped.
      if (mapped.length > 0 && mapped.length < 1000) {
        q = q.not('eurio_id', 'in', `(${mapped.map(id => `"${id}"`).join(',')})`)
      }
    } else {
      const zone = filterZone.value
      const ids = mapped.filter(id => confusionZones.value.get(id)?.zone === zone)
      if (ids.length === 0) {
        // Shortcut: no matches → empty list
        coins.value = append ? coins.value : []
        total.value = append ? total.value : 0
        loading.value = false
        return
      }
      q = q.in('eurio_id', ids)
    }
  }

  q = q
    .order('country')
    .order('year', { ascending: false })
    .order('face_value', { ascending: false })
    .range(offset.value, offset.value + PAGE - 1)

  const { data, error: err, count } = await q

  loading.value = false
  if (err) { error.value = err.message; return }

  if (append) {
    coins.value = [...coins.value, ...(data ?? []) as Coin[]]
  } else {
    coins.value = (data ?? []) as Coin[]
  }
  total.value = count ?? 0
}

function loadMore() {
  offset.value += PAGE
  fetchCoins(query.value, true)
}

function resetAndFetch() {
  offset.value = 0
  fetchCoins(query.value)
}

function buildUrlQuery(): Record<string, string> {
  const q: Record<string, string> = {}
  if (query.value) q.q = query.value
  if (filterCountries.value.size > 0) q.countries = [...filterCountries.value].sort().join(',')
  if (filterFaceValue.value != null) q.fv = String(filterFaceValue.value)
  if (filterCommemo.value != null) q.commemo = String(filterCommemo.value)
  if (filterNumista.value) q.numista = filterNumista.value
  if (filterImages.value) q.images = filterImages.value
  if (filterSources.value.size > 0) q.sources = [...filterSources.value].sort().join(',')
  if (filterZone.value) q.zone = filterZone.value
  if (filterTrained.value) q.trained = filterTrained.value
  if (filterPersonal.value) q.personal = filterPersonal.value
  return q
}

const debouncedFetch = useDebounceFn(() => resetAndFetch(), 250)
watch(query, debouncedFetch)
watch([filterCountries, filterFaceValue, filterCommemo, filterNumista, filterImages, filterZone, filterTrained, filterPersonal, filterSources],
  resetAndFetch, { deep: true })
watch(
  [query, filterCountries, filterFaceValue, filterCommemo, filterNumista, filterImages, filterZone, filterTrained, filterPersonal, filterSources],
  () => router.replace({ query: buildUrlQuery() }),
  { deep: true },
)
onMounted(async () => {
  // Load zones FIRST so the in-memory filter has data before initial fetch
  await fetchConfusionZones()
  fetchSourceCounts()
  fetchCoins()
  fetchTrainedIds()
  checkMlApi()
  mlApiInterval = setInterval(checkMlApi, 30_000)
})

onUnmounted(() => {
  clearInterval(mlApiInterval)
})

function goDetail(eurio_id: string) {
  router.push(`/coins/${encodeURIComponent(eurio_id)}`)
}

function formatFaceValue(v: number): string {
  if (v >= 1) return `${v.toFixed(0)}€`
  return `${(v * 100).toFixed(0)}¢`
}

function hasNumistaId(coin: Coin): boolean {
  return coin.cross_refs?.numista_id != null
}

function clearFilters() {
  filterCountries.value = new Set()
  filterFaceValue.value = null
  filterCommemo.value = null
  filterNumista.value = null
  filterImages.value = null
  filterZone.value = null
  filterTrained.value = null
  filterPersonal.value = null
  filterSources.value = new Set()
  query.value = ''
}

function toggleCountry(c: string) {
  const s = new Set(filterCountries.value)
  if (s.has(c)) s.delete(c)
  else s.add(c)
  filterCountries.value = s
}

function toggleSource(s: SourceKey) {
  const next = new Set(filterSources.value)
  if (next.has(s)) next.delete(s)
  else next.add(s)
  filterSources.value = next
}

const SOURCE_LABELS: Record<SourceKey, string> = {
  numista:   'Numista',
  bce:       'BCE',
  wikipedia: 'Wikipedia',
  lmdlp:     'LMDLP',
  ebay:      'eBay',
}

// Source row counts shown in the chips. Cheap: one HEAD per source, all in
// parallel. Numista is the only one not backed by a `has_*` column — count
// rows where cross_refs->numista_id is set.
const sourceCounts = ref<Partial<Record<SourceKey, number>>>({})

async function fetchSourceCounts() {
  const queries: Array<Promise<void>> = SOURCE_KEYS.map(async (src) => {
    let q = supabase.from('coins').select('eurio_id', { count: 'exact', head: true })
    if (src === 'numista') q = q.not('cross_refs->numista_id', 'is', null)
    else if (src === 'bce') q = q.eq('has_bce', true)
    else if (src === 'wikipedia') q = q.eq('has_wikipedia', true)
    else if (src === 'lmdlp') q = q.eq('has_lmdlp', true)
    else if (src === 'ebay') q = q.eq('has_ebay', true)
    const { count } = await q
    sourceCounts.value = { ...sourceCounts.value, [src]: count ?? 0 }
  })
  await Promise.all(queries)
}

// Training status
const trainedEurioIds = ref<Set<string>>(new Set())

// Confusion-map zones (Phase 1 ML scalability)
const confusionZones = ref<Map<string, { zone: ConfusionZone, nearest_similarity: number }>>(new Map())

async function fetchConfusionZones() {
  try {
    confusionZones.value = await fetchZoneMap()
  } catch {
    // silent — zone filter/badge just becomes inert
  }
}

function coinZone(coin: Coin): { zone: ConfusionZone, nearest_similarity: number } | null {
  return confusionZones.value.get(coin.eurio_id) ?? null
}

async function fetchTrainedIds() {
  const { data } = await supabase
    .from('coin_embeddings')
    .select('eurio_id') as { data: { eurio_id: string }[] | null }
  if (data) {
    trainedEurioIds.value = new Set(data.map(e => e.eurio_id))
  }
}

function isTrained(coin: Coin): boolean {
  return trainedEurioIds.value.has(coin.eurio_id)
}

const hasActiveFilters = () =>
  filterCountries.value.size > 0 || filterFaceValue.value != null || filterCommemo.value != null
  || filterNumista.value != null || filterImages.value != null || filterZone.value != null
  || filterTrained.value != null || filterPersonal.value != null || filterSources.value.size > 0
  || query.value

// ─── Training staging ───
//
// A "class" is the ArcFace label: design_group_id when the coin belongs to a
// shared-design grouping, else eurio_id. Clicking any coin toggles its class_id;
// all sibling coins sharing the same design_group_id light up visually for free.

type ClassKind = 'eurio_id' | 'design_group_id'

const ML_API = 'http://localhost:8042'
const mlApiOnline = ref(false)
const selectedClasses = ref<Set<string>>(new Set())
const selectedClassKinds = ref<Map<string, ClassKind>>(new Map())
const enqueueLoading = ref(false)
const enqueueSuccess = ref(false)
const enqueueStagedCount = ref(0)

async function checkMlApi() {
  try {
    const resp = await fetch(`${ML_API}/health`, { signal: AbortSignal.timeout(3000) })
    mlApiOnline.value = resp.ok
  } catch {
    mlApiOnline.value = false
  }
}

let mlApiInterval: ReturnType<typeof setInterval>

function coinClassId(coin: Coin): string {
  return coin.design_group_id || coin.eurio_id
}

function coinClassKind(coin: Coin): ClassKind {
  return coin.design_group_id ? 'design_group_id' : 'eurio_id'
}

function isSelected(coin: Coin): boolean {
  return selectedClasses.value.has(coinClassId(coin))
}

function canStage(coin: Coin): boolean {
  // Need a Numista mapping somewhere in the class to drive augmentation.
  // Either the coin itself has one, or it belongs to a design_group (which
  // necessarily contains at least one member with a numista_id).
  return !!coin.cross_refs?.numista_id || !!coin.design_group_id
}

function toggleSelection(coin: Coin, event: Event) {
  event.stopPropagation()
  if (!canStage(coin)) return
  const classId = coinClassId(coin)
  const s = new Set(selectedClasses.value)
  const m = new Map(selectedClassKinds.value)
  if (s.has(classId)) {
    s.delete(classId)
    m.delete(classId)
  } else {
    s.add(classId)
    m.set(classId, coinClassKind(coin))
  }
  selectedClasses.value = s
  selectedClassKinds.value = m
}

const selectedCount = computed(() => selectedClasses.value.size)

// ─── Personal collection toggle ───
//
// Direct toggle (no batch footer): clicking the wallet checkbox flips
// `coins.personal_owned` immediately on Supabase, with optimistic local
// update so the UI feels instant. On error we revert the local row and
// surface an error chip — the user can re-tap to retry. A Set of
// in-flight eurio_ids prevents double-tap races.
const personalSaving = ref<Set<string>>(new Set())

async function togglePersonal(coin: Coin, event: Event) {
  event.stopPropagation()
  if (personalSaving.value.has(coin.eurio_id)) return
  const prev = !!coin.personal_owned
  const next = !prev

  // Optimistic local update — patch the array in place so the wrapping
  // ref triggers reactivity without re-fetching the page.
  const idx = coins.value.findIndex(c => c.eurio_id === coin.eurio_id)
  if (idx >= 0) coins.value[idx] = { ...coins.value[idx], personal_owned: next }
  personalSaving.value = new Set([...personalSaving.value, coin.eurio_id])

  try {
    const { error: err } = await supabase
      .from('coins')
      .update({ personal_owned: next })
      .eq('eurio_id', coin.eurio_id)
    if (err) throw err
  } catch (e) {
    // Revert on failure — the user sees the checkbox snap back to
    // its previous state and the error message at the top of the page.
    if (idx >= 0) coins.value[idx] = { ...coins.value[idx], personal_owned: prev }
    error.value = `Personal toggle failed: ${(e as Error).message}`
  } finally {
    const s = new Set(personalSaving.value)
    s.delete(coin.eurio_id)
    personalSaving.value = s
  }
}

const AUGMENT_CAP = 20

// Resolve eurio_ids for the selected set, falling back to displayed coin rows.
// This skips any class whose coin row isn't currently visible (rare edge case).
const augmentEurioIds = computed<string[]>(() => {
  const byClass = new Map(coins.value.map(c => [coinClassId(c), c]))
  const ids: string[] = []
  for (const cid of selectedClasses.value) {
    const coin = byClass.get(cid)
    if (coin) ids.push(coin.eurio_id)
  }
  return ids
})

const augmentOverCap = computed(() => augmentEurioIds.value.length > AUGMENT_CAP)
const augmentDisabled = computed(
  () => !mlApiOnline.value || augmentEurioIds.value.length === 0 || augmentOverCap.value,
)
const augmentTitle = computed(() => {
  if (augmentOverCap.value) return `Maximum ${AUGMENT_CAP} pièces — désélectionne avant d’augmenter`
  if (!mlApiOnline.value) return 'ML API hors-ligne'
  return 'Ouvre le Studio d’augmentation sur la sélection'
})

const cohortDisabled = computed(
  () => !mlApiOnline.value || augmentEurioIds.value.length === 0,
)
const cohortTitle = computed(() => {
  if (augmentEurioIds.value.length === 0) return 'Sélectionne au moins une pièce'
  if (!mlApiOnline.value) return 'ML API hors-ligne'
  return 'Crée un cohort Lab pré-rempli avec la sélection'
})
function openCohortWizard() {
  if (cohortDisabled.value) return
  const ids = augmentEurioIds.value.join(',')
  router.push(`/lab/cohorts/new?eurio_ids=${ids}`)
}

function openAugmentation() {
  if (augmentDisabled.value) return
  const ids = augmentEurioIds.value.slice(0, AUGMENT_CAP).join(',')
  router.push(`/augmentation?eurio_ids=${ids}`)
}

async function enqueueSelected(andNavigate = false) {
  if (!mlApiOnline.value || selectedClasses.value.size === 0) return
  enqueueLoading.value = true
  try {
    const items = Array.from(selectedClasses.value).map(class_id => ({
      class_id,
      class_kind: selectedClassKinds.value.get(class_id) ?? 'eurio_id',
    }))
    const resp = await fetch(`${ML_API}/training/stage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items }),
    })
    if (resp.ok) {
      enqueueStagedCount.value = items.length
      enqueueSuccess.value = true
      selectedClasses.value = new Set()
      selectedClassKinds.value = new Map()
      if (andNavigate) {
        router.push('/training')
        return
      }
      setTimeout(() => { enqueueSuccess.value = false }, 4000)
    }
  } catch {
    // ignore
  } finally {
    enqueueLoading.value = false
  }
}

function clearSelection() {
  selectedClasses.value = new Set()
  selectedClassKinds.value = new Map()
}

// ─── Clipboard copy ───

const copiedToast = ref<{ label: string, value: string } | null>(null)
let copiedToastTimer: ReturnType<typeof setTimeout> | null = null

function copyToClipboard(value: string, label: string, event: Event) {
  event.stopPropagation()
  navigator.clipboard?.writeText(value)
  copiedToast.value = { label, value }
  if (copiedToastTimer) clearTimeout(copiedToastTimer)
  copiedToastTimer = setTimeout(() => { copiedToast.value = null }, 1500)
}
</script>

<template>
  <div class="p-8">
    <div class="mb-6 flex items-start justify-between">
      <div>
        <h1 class="font-display text-2xl italic font-semibold"
            style="color: var(--indigo-700);">
          Référentiel pièces
        </h1>
        <p class="mt-0.5 text-sm" style="color: var(--ink-500);">
          {{ total.toLocaleString('fr-FR') }} pièces
          <template v-if="hasActiveFilters()"> (filtrées)</template>
          · lecture seule (géré via ml/bootstrap)
        </p>
      </div>
      <button
        v-if="hasActiveFilters()"
        class="rounded-md px-3 py-1.5 text-xs font-medium transition-colors"
        style="background: var(--surface-1); color: var(--ink-500);"
        @click="clearFilters"
      >
        Effacer filtres
      </button>
    </div>

    <!-- Search -->
    <div class="relative mb-4 max-w-md">
      <Search class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2"
              style="color: var(--ink-400);" />
      <input
        v-model="query"
        type="search"
        placeholder="eurio_id, thème, pays, numista_id (226447)…"
        class="w-full rounded-md border py-2 pl-9 pr-3 text-sm outline-none focus:ring-2"
        style="border-color: var(--surface-3); background: var(--surface); color: var(--ink); --tw-ring-color: var(--indigo-700);"
      />
    </div>

    <!-- Filters -->
    <div class="mb-6 flex flex-wrap items-center gap-3">
      <!-- Countries (multi-select chips, cumulable) -->
      <div class="flex flex-wrap items-center gap-1">
        <span
          class="mr-1 text-[10px] font-medium uppercase"
          style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);"
        >
          Pays
        </span>
        <button
          v-for="c in COUNTRIES" :key="c"
          class="rounded-full border px-2 py-1 text-[11px] font-mono font-medium transition-colors"
          :style="{
            background: filterCountries.has(c) ? 'var(--indigo-700)' : 'var(--surface)',
            color: filterCountries.has(c) ? 'white' : 'var(--ink-500)',
            borderColor: filterCountries.has(c) ? 'var(--indigo-700)' : 'var(--surface-3)',
          }"
          @click="toggleCountry(c)"
        >
          {{ c }}
        </button>
      </div>

      <!-- Denomination chips -->
      <div class="flex flex-wrap gap-1">
        <button
          v-for="d in DENOMINATIONS" :key="d"
          class="rounded-full border px-2.5 py-1 text-[11px] font-mono font-medium transition-colors"
          :style="{
            background: filterFaceValue === d ? 'var(--indigo-700)' : 'var(--surface)',
            color: filterFaceValue === d ? 'white' : 'var(--ink-500)',
            borderColor: filterFaceValue === d ? 'var(--indigo-700)' : 'var(--surface-3)',
          }"
          @click="filterFaceValue = filterFaceValue === d ? null : d"
        >
          {{ formatFaceValue(d) }}
        </button>
      </div>

      <!-- Separator -->
      <div class="h-5 w-px" style="background: var(--surface-3);" />

      <!-- Type chips -->
      <div class="flex gap-1">
        <button
          class="rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors"
          :style="{
            background: filterCommemo === false ? 'var(--indigo-700)' : 'var(--surface)',
            color: filterCommemo === false ? 'white' : 'var(--ink-500)',
            borderColor: filterCommemo === false ? 'var(--indigo-700)' : 'var(--surface-3)',
          }"
          @click="filterCommemo = filterCommemo === false ? null : false"
        >
          Circulation
        </button>
        <button
          class="rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors"
          :style="{
            background: filterCommemo === true ? 'var(--indigo-700)' : 'var(--surface)',
            color: filterCommemo === true ? 'white' : 'var(--ink-500)',
            borderColor: filterCommemo === true ? 'var(--indigo-700)' : 'var(--surface-3)',
          }"
          @click="filterCommemo = filterCommemo === true ? null : true"
        >
          Commémo
        </button>
      </div>

      <!-- Separator -->
      <div class="h-5 w-px" style="background: var(--surface-3);" />

      <!-- Data quality chips -->
      <div class="flex gap-1">
        <button
          v-for="opt in ([
            { key: 'with' as const, label: 'Numista ID', ref: filterNumista },
            { key: 'without' as const, label: 'Sans Numista', ref: filterNumista },
          ])" :key="opt.key + '-numista'"
          class="rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors"
          :style="{
            background: filterNumista === opt.key ? (opt.key === 'with' ? '#059669' : '#dc2626') : 'var(--surface)',
            color: filterNumista === opt.key ? 'white' : 'var(--ink-500)',
            borderColor: filterNumista === opt.key ? 'transparent' : 'var(--surface-3)',
          }"
          @click="filterNumista = filterNumista === opt.key ? null : opt.key"
        >
          {{ opt.label }}
        </button>
      </div>

      <div class="flex gap-1">
        <button
          v-for="opt in ([
            { key: 'with' as const, label: 'Avec image' },
            { key: 'without' as const, label: 'Sans image' },
          ])" :key="opt.key + '-images'"
          class="rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors"
          :style="{
            background: filterImages === opt.key ? (opt.key === 'with' ? '#059669' : '#dc2626') : 'var(--surface)',
            color: filterImages === opt.key ? 'white' : 'var(--ink-500)',
            borderColor: filterImages === opt.key ? 'transparent' : 'var(--surface-3)',
          }"
          @click="filterImages = filterImages === opt.key ? null : opt.key"
        >
          {{ opt.label }}
        </button>
      </div>

      <!-- Separator -->
      <div class="h-5 w-px" style="background: var(--surface-3);" />

      <!-- Sources (cumulable, AND across active sources) -->
      <div class="flex items-center gap-1">
        <span
          class="mr-1 text-[10px] font-medium uppercase"
          style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);"
          title="Filtre cumulable : la pièce doit avoir une donnée de chaque source active"
        >
          Sources
        </span>
        <button
          v-for="s in SOURCE_KEYS" :key="s"
          class="flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors"
          :style="{
            background: filterSources.has(s) ? 'var(--indigo-700)' : 'var(--surface)',
            color: filterSources.has(s) ? 'white' : 'var(--ink-500)',
            borderColor: filterSources.has(s) ? 'var(--indigo-700)' : 'var(--surface-3)',
          }"
          @click="toggleSource(s)"
        >
          {{ SOURCE_LABELS[s] }}
          <span
            v-if="sourceCounts[s] != null"
            class="font-mono text-[10px]"
            :style="{ color: filterSources.has(s) ? 'rgba(255,255,255,0.7)' : 'var(--ink-400)' }"
          >
            {{ sourceCounts[s] }}
          </span>
        </button>
      </div>

      <!-- Separator -->
      <div class="h-5 w-px" style="background: var(--surface-3);" />

      <!-- Training status chips -->
      <div class="flex items-center gap-1">
        <span
          class="mr-1 text-[10px] font-medium uppercase"
          style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);"
          title="Statut d'entraînement dans le modèle ArcFace courant"
        >
          Modèle ML
        </span>
        <button
          v-for="opt in ([
            { key: 'trained' as const, label: 'Entraînées', color: 'var(--indigo-700)' },
            { key: 'not-trained' as const, label: 'Non entraînées', color: 'var(--ink-400)' },
          ])" :key="opt.key + '-trained'"
          class="flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors"
          :style="{
            background: filterTrained === opt.key ? opt.color : 'var(--surface)',
            color: filterTrained === opt.key ? 'white' : 'var(--ink-500)',
            borderColor: filterTrained === opt.key ? 'transparent' : 'var(--surface-3)',
          }"
          @click="filterTrained = filterTrained === opt.key ? null : opt.key"
        >
          <Brain v-if="opt.key === 'trained'" class="h-3 w-3" />
          {{ opt.label }}
        </button>
      </div>

      <!-- Separator -->
      <div class="h-5 w-px" style="background: var(--surface-3);" />

      <!-- Personal collection chips (admin's owned coins, see migration 20260428) -->
      <div class="flex items-center gap-1">
        <span
          class="mr-1 text-[10px] font-medium uppercase"
          style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);"
          title="Pièces marquées comme étant dans ta collection physique (toggle wallet sur chaque carte)"
        >
          Collection
        </span>
        <button
          v-for="opt in ([
            { key: 'owned' as const, label: 'Dans ma collec', color: 'var(--success)' },
            { key: 'not-owned' as const, label: 'Pas dans ma collec', color: 'var(--ink-400)' },
          ])" :key="opt.key + '-personal'"
          class="flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors"
          :style="{
            background: filterPersonal === opt.key ? opt.color : 'var(--surface)',
            color: filterPersonal === opt.key ? 'white' : 'var(--ink-500)',
            borderColor: filterPersonal === opt.key ? 'transparent' : 'var(--surface-3)',
          }"
          @click="filterPersonal = filterPersonal === opt.key ? null : opt.key"
        >
          <Wallet v-if="opt.key === 'owned'" class="h-3 w-3" />
          {{ opt.label }}
        </button>
      </div>

      <!-- Separator -->
      <div v-if="confusionZones.size > 0" class="h-5 w-px" style="background: var(--surface-3);" />

      <!-- Zone chips (Phase 1 ML scalability) -->
      <div v-if="confusionZones.size > 0" class="flex items-center gap-1">
        <span
          class="mr-1 text-[10px] font-medium uppercase"
          style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);"
          title="Cartographie de confusion (voir /confusion)"
        >
          Zone
        </span>
        <button
          v-for="opt in ([
            { key: 'green' as const, label: 'Verte', color: 'var(--success)' },
            { key: 'orange' as const, label: 'Orange', color: 'var(--warning)' },
            { key: 'red' as const, label: 'Rouge', color: 'var(--danger)' },
            { key: 'unmapped' as const, label: 'Non cart.', color: 'var(--ink-400)' },
          ])" :key="opt.key"
          class="flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors"
          :style="{
            background: filterZone === opt.key ? opt.color : 'var(--surface)',
            color: filterZone === opt.key ? 'white' : 'var(--ink-500)',
            borderColor: filterZone === opt.key ? 'transparent' : 'var(--surface-3)',
          }"
          @click="filterZone = filterZone === opt.key ? null : opt.key"
        >
          <span
            v-if="opt.key !== 'unmapped'"
            class="h-1.5 w-1.5 rounded-full"
            :style="{ background: filterZone === opt.key ? 'white' : opt.color }"
          />
          {{ opt.label }}
        </button>
      </div>
    </div>

    <div v-if="error"
         class="mb-4 rounded-md px-4 py-3 text-sm"
         style="background: var(--danger-soft); color: var(--danger);">
      {{ error }}
    </div>

    <!-- Loading -->
    <div v-if="loading && coins.length === 0" class="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
      <div v-for="i in 12" :key="i"
           class="aspect-square animate-pulse rounded-lg"
           style="background: var(--surface-1);" />
    </div>

    <!-- Empty -->
    <div v-else-if="coins.length === 0"
         class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed py-16"
         style="border-color: var(--surface-3);">
      <p class="font-display italic text-lg" style="color: var(--ink-400);">
        Aucune pièce trouvée
      </p>
    </div>

    <!-- Grid -->
    <div v-else class="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
      <button
        v-for="coin in coins"
        :key="coin.eurio_id"
        class="group flex flex-col overflow-hidden rounded-lg border text-left transition-all hover:-translate-y-0.5"
        style="border-color: var(--surface-3); background: var(--surface); box-shadow: var(--shadow-sm);"
        @click="goDetail(coin.eurio_id)"
      >
        <!-- Thumbnail -->
        <div
          class="relative flex aspect-square items-center justify-center"
          style="background: var(--surface-1);"
        >
          <img
            v-if="firstImageUrl(coin)"
            :src="firstImageUrl(coin)!"
            :alt="coin.theme ?? coin.eurio_id"
            class="h-full w-full object-contain p-3 transition-transform duration-300 group-hover:scale-105"
            loading="lazy"
          />
          <div v-else class="flex flex-col items-center gap-1" style="color: var(--ink-300);">
            <ImageOff class="h-6 w-6" />
            <span class="text-[10px] uppercase tracking-wider">pas d'image</span>
          </div>

          <!-- Selection checkbox (coins stageable for training) -->
          <div
            v-if="canStage(coin) && mlApiOnline"
            class="absolute left-2 top-2 z-10 flex h-5 w-5 items-center justify-center rounded transition-opacity"
            :class="isSelected(coin) ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'"
            :style="{
              background: isSelected(coin)
                ? 'var(--indigo-700)' : 'rgba(255,255,255,0.9)',
              border: isSelected(coin)
                ? 'none' : '1.5px solid var(--surface-3)',
            }"
            :title="coin.design_group_id
              ? `Design partagé : toutes les pièces de ${coin.design_group_id} seront ajoutées`
              : 'Ajouter au prochain entraînement'"
            @click="toggleSelection(coin, $event)"
          >
            <Check
              v-if="isSelected(coin)"
              class="h-3 w-3"
              style="color: white"
            />
          </div>

          <!-- Personal-collection toggle (wallet icon background).
               Direct toggle: tap = flip personal_owned on Supabase. Sits next
               to the training checkbox (left-9) when training is shown, else
               takes its place at left-2. Always visible (every coin can be
               in the user's physical collection regardless of trainability)
               but uses opacity-0/100 to fade in on hover unless already on,
               same pattern as training checkbox. -->
          <div
            class="absolute top-2 z-10 flex h-5 w-5 items-center justify-center rounded transition-opacity"
            :class="[
              canStage(coin) && mlApiOnline ? 'left-9' : 'left-2',
              coin.personal_owned ? 'opacity-100' : 'opacity-0 group-hover:opacity-100',
              personalSaving.has(coin.eurio_id) ? 'pointer-events-none' : '',
            ]"
            :style="{
              background: coin.personal_owned
                ? 'var(--success)' : 'rgba(255,255,255,0.9)',
              border: coin.personal_owned
                ? 'none' : '1.5px solid var(--surface-3)',
              opacity: personalSaving.has(coin.eurio_id) ? '0.6' : undefined,
            }"
            :title="coin.personal_owned
              ? 'Dans ta collection physique — clique pour retirer'
              : 'Ajouter à ta collection physique'"
            @click="togglePersonal(coin, $event)"
          >
            <Wallet
              class="h-3 w-3"
              :style="{ color: coin.personal_owned ? 'white' : 'var(--ink-400)' }"
            />
          </div>

          <!-- Face value badge — shifts right based on which checkboxes are
               visible above it. Both shown: left-16. One shown: left-9.
               Neither (rare — would need !canStage AND no hover): left-2. -->
          <span
            class="absolute rounded-full px-2 py-0.5 text-[10px] font-mono font-medium"
            :class="canStage(coin) && mlApiOnline ? 'left-16 top-2' : 'left-9 top-2'"
            style="background: var(--indigo-700); color: white;"
          >
            {{ formatFaceValue(coin.face_value) }}
          </span>

          <!-- Country badge -->
          <span
            class="absolute right-2 top-2 rounded-full px-2 py-0.5 text-[10px] font-mono font-bold uppercase"
            style="background: rgba(255,255,255,0.92); color: var(--ink);"
          >
            {{ coin.country }}
          </span>

          <!-- EurioID label (always present, click to copy full slug) -->
          <div
            role="button"
            tabindex="0"
            class="absolute left-2 flex cursor-pointer items-center gap-1 rounded-full border px-1.5 py-0.5 text-[9px] font-mono font-medium transition-colors hover:border-current"
            :class="hasNumistaId(coin) ? 'bottom-8' : 'bottom-2'"
            style="background: rgba(255,255,255,0.92); color: var(--ink); border-color: var(--surface-3);"
            :title="`Copier ${coin.eurio_id}`"
            @click="copyToClipboard(coin.eurio_id, 'EurioID', $event)"
          >
            <Copy class="h-2.5 w-2.5" />
            EurioID
          </div>

          <!-- Numista badge (click to copy numista_id) -->
          <div
            v-if="hasNumistaId(coin)"
            role="button"
            tabindex="0"
            class="absolute bottom-2 left-2 flex cursor-pointer items-center gap-1 rounded-full px-1.5 py-0.5 text-[9px] font-mono font-medium"
            style="background: #059669; color: white;"
            :title="`Copier ${coin.cross_refs.numista_id}`"
            @click="copyToClipboard(String(coin.cross_refs.numista_id), 'NumistaID', $event)"
          >
            N{{ coin.cross_refs.numista_id }}
            <Copy class="h-2.5 w-2.5 opacity-80" />
          </div>

          <!-- Training badge -->
          <span
            v-if="isTrained(coin)"
            class="absolute bottom-2 right-2 flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[9px] font-medium"
            style="background: var(--indigo-700); color: white;"
            title="Design entraîné"
          >
            <Brain class="h-2.5 w-2.5" />
            ML
          </span>

          <!-- Zone badge (Phase 1 ML scalability) -->
          <span
            v-if="coinZone(coin)"
            :class="isTrained(coin) ? 'absolute bottom-2 right-11' : 'absolute bottom-2 right-2'"
            class="flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[9px] font-mono font-medium"
            :style="{
              background: 'rgba(255,255,255,0.92)',
              color: zoneStyle(coinZone(coin)!.zone).solid,
            }"
            :title="`${zoneStyle(coinZone(coin)!.zone).label} · voisin @ ${coinZone(coin)!.nearest_similarity.toFixed(3)}`"
          >
            <span
              class="h-1.5 w-1.5 rounded-full"
              :style="{ background: zoneStyle(coinZone(coin)!.zone).solid }"
            />
            {{ zoneStyle(coinZone(coin)!.zone).short }}
          </span>
        </div>

        <!-- Meta -->
        <div class="flex flex-1 flex-col justify-between p-3">
          <div>
            <p class="text-xs font-mono" style="color: var(--ink-400);">
              {{ coin.year }}
            </p>
            <p class="mt-0.5 line-clamp-2 text-xs font-medium leading-snug" style="color: var(--ink);">
              {{ coin.theme ?? '—' }}
            </p>
          </div>
          <p
            v-if="coin.issue_type"
            class="mt-2 text-[10px] uppercase tracking-wider"
            style="color: var(--ink-500);"
          >
            {{ issueLabel[coin.issue_type] }}
          </p>
        </div>
      </button>
    </div>

    <!-- Load more -->
    <div v-if="!loading && coins.length > 0 && coins.length < total"
         class="mt-6 flex flex-col items-center gap-1">
      <button
        class="rounded-md border px-4 py-2 text-sm font-medium transition-colors hover:border-current"
        style="border-color: var(--surface-3); color: var(--indigo-700);"
        :disabled="loading"
        @click="loadMore"
      >
        Charger plus
      </button>
      <p class="text-[11px]" style="color: var(--ink-400);">
        {{ coins.length }} sur {{ total.toLocaleString('fr-FR') }}
      </p>
    </div>

    <!-- Loading indicator for load more -->
    <div v-if="loading && coins.length > 0" class="mt-6 flex justify-center">
      <div class="h-6 w-6 animate-spin rounded-full border-2 border-current border-t-transparent"
           style="color: var(--indigo-700);" />
    </div>

    <!-- Sticky bottom bar for training staging -->
    <Teleport to="body">
      <Transition name="slide-up">
        <div
          v-if="selectedCount > 0"
          class="fixed bottom-0 left-60 right-0 z-40 border-t px-8 py-3"
          style="background: var(--surface); border-color: var(--surface-3); box-shadow: 0 -4px 12px rgba(0,0,0,0.08)"
        >
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-3">
              <span class="text-sm font-medium" style="color: var(--ink)">
                {{ selectedCount }} design{{ selectedCount > 1 ? 's' : '' }} à ajouter
              </span>
              <button
                class="text-xs underline"
                style="color: var(--ink-500)"
                @click="clearSelection"
              >
                Annuler
              </button>
            </div>
            <div class="flex items-center gap-3">
              <button
                class="rounded-md px-3 py-2 text-sm font-medium transition-all"
                style="background: var(--surface-1); color: var(--ink)"
                :disabled="enqueueLoading"
                @click="enqueueSelected(true)"
              >
                Ajouter et voir →
              </button>
              <button
                class="flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-all"
                :style="{
                  background: 'var(--surface-1)',
                  color: augmentDisabled ? 'var(--ink-400)' : 'var(--ink)',
                  cursor: augmentDisabled ? 'not-allowed' : 'pointer',
                  opacity: augmentDisabled ? 0.6 : 1,
                }"
                :disabled="augmentDisabled"
                :title="augmentTitle"
                @click="openAugmentation"
              >
                <Sparkles class="h-3.5 w-3.5" />
                Augmenter
                <span
                  v-if="augmentOverCap"
                  class="ml-1 rounded px-1 text-[10px] font-mono"
                  style="background: var(--danger); color: white;"
                >{{ AUGMENT_CAP }} max</span>
              </button>
              <button
                class="flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-all"
                :style="{
                  background: 'var(--surface-1)',
                  color: cohortDisabled ? 'var(--ink-400)' : 'var(--ink)',
                  cursor: cohortDisabled ? 'not-allowed' : 'pointer',
                  opacity: cohortDisabled ? 0.6 : 1,
                }"
                :disabled="cohortDisabled"
                :title="cohortTitle"
                @click="openCohortWizard"
              >
                <FlaskConical class="h-3.5 w-3.5" />
                Nouveau cohort Lab
              </button>
              <button
                class="flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-all"
                style="background: var(--indigo-700); color: white"
                :disabled="enqueueLoading"
                @click="enqueueSelected(false)"
              >
                <Play class="h-3.5 w-3.5" />
                Ajouter au training
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Clipboard copy toast -->
    <Teleport to="body">
      <Transition name="slide-up">
        <div
          v-if="copiedToast"
          class="fixed bottom-4 left-1/2 z-50 flex -translate-x-1/2 items-center gap-2 rounded-md border px-3 py-2 text-xs"
          style="background: var(--surface); border-color: var(--surface-3); box-shadow: var(--shadow-md); color: var(--ink)"
        >
          <Check class="h-3 w-3" style="color: var(--success)" />
          <span><strong>{{ copiedToast.label }}</strong> copié</span>
          <code
            class="truncate rounded px-1.5 py-0.5 font-mono text-[10px]"
            style="background: var(--surface-1); color: var(--ink-500); max-width: 320px;"
          >{{ copiedToast.value }}</code>
        </div>
      </Transition>
    </Teleport>

    <!-- Success toast with navigate action -->
    <Teleport to="body">
      <Transition name="slide-up">
        <div
          v-if="enqueueSuccess && selectedCount === 0"
          class="fixed bottom-4 right-4 z-50 flex items-center gap-3 rounded-md border px-4 py-3 text-sm"
          style="background: var(--surface); border-color: var(--success); box-shadow: var(--shadow-md); color: var(--ink)"
        >
          <span>
            <strong>{{ enqueueStagedCount }}</strong> design{{ enqueueStagedCount > 1 ? 's' : '' }} ajouté{{ enqueueStagedCount > 1 ? 's' : '' }} au prochain entraînement
          </span>
          <button
            class="text-xs font-medium underline"
            style="color: var(--indigo-700)"
            @click="router.push('/training')"
          >
            Voir →
          </button>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.slide-up-enter-active,
.slide-up-leave-active {
  transition: transform 0.2s ease, opacity 0.2s ease;
}
.slide-up-enter-from,
.slide-up-leave-to {
  transform: translateY(100%);
  opacity: 0;
}
</style>
