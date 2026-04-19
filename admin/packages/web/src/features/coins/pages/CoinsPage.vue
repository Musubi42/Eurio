<script setup lang="ts">
import { fetchZoneMap } from '@/features/confusion/composables/useConfusionMap'
import { zoneStyle } from '@/features/confusion/composables/useConfusionZone'
import { supabase } from '@/shared/supabase/client'
import type { Coin, ConfusionZone, IssueType } from '@/shared/supabase/types'
import { firstImageUrl } from '@/shared/utils/coin-images'
import { useDebounceFn } from '@vueuse/core'
import { Brain, Check, Copy, ImageOff, Play, Search } from 'lucide-vue-next'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const coins = ref<Coin[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const query = ref('')
const total = ref(0)
const offset = ref(0)
const PAGE = 60

// Filters
const filterCountry = ref<string>('')
const filterFaceValue = ref<number | null>(null)
const filterCommemo = ref<boolean | null>(null)
const filterNumista = ref<'with' | 'without' | null>(null)
const filterImages = ref<'with' | 'without' | null>(null)
const filterZone = ref<ConfusionZone | 'unmapped' | null>(null)
const filterTrained = ref<'trained' | 'not-trained' | null>(null)

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
  if (filterCountry.value) q = q.eq('country', filterCountry.value)
  if (filterFaceValue.value != null) q = q.eq('face_value', filterFaceValue.value)
  if (filterCommemo.value != null) q = q.eq('is_commemorative', filterCommemo.value)
  if (filterNumista.value === 'with') q = q.not('cross_refs->numista_id', 'is', null)
  if (filterNumista.value === 'without') q = q.is('cross_refs->numista_id', null)
  if (filterImages.value === 'with') q = q.neq('images', '[]').not('images', 'is', null)
  if (filterImages.value === 'without') q = q.or('images.eq.[],images.is.null')

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

const debouncedFetch = useDebounceFn(() => resetAndFetch(), 250)
watch(query, debouncedFetch)
watch([filterCountry, filterFaceValue, filterCommemo, filterNumista, filterImages, filterZone, filterTrained], resetAndFetch)
onMounted(async () => {
  // Load zones FIRST so the in-memory filter has data before initial fetch
  await fetchConfusionZones()
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
  filterCountry.value = ''
  filterFaceValue.value = null
  filterCommemo.value = null
  filterNumista.value = null
  filterImages.value = null
  filterZone.value = null
  filterTrained.value = null
  query.value = ''
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
  filterCountry.value || filterFaceValue.value != null || filterCommemo.value != null
  || filterNumista.value != null || filterImages.value != null || filterZone.value != null
  || filterTrained.value != null
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
      <!-- Country -->
      <select
        v-model="filterCountry"
        class="rounded-md border px-2 py-1.5 text-xs font-mono outline-none focus:ring-2"
        style="border-color: var(--surface-3); background: var(--surface); color: var(--ink); --tw-ring-color: var(--indigo-700);"
      >
        <option value="">Tous pays</option>
        <option v-for="c in COUNTRIES" :key="c" :value="c">{{ c }}</option>
      </select>

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

          <!-- Face value badge -->
          <span
            class="absolute rounded-full px-2 py-0.5 text-[10px] font-mono font-medium"
            :class="canStage(coin) && mlApiOnline ? 'left-9 top-2' : 'left-2 top-2'"
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
