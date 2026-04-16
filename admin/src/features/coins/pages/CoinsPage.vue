<script setup lang="ts">
import { supabase } from '@/shared/supabase/client'
import type { Coin, IssueType } from '@/shared/supabase/types'
import { firstImageUrl } from '@/shared/utils/coin-images'
import { useDebounceFn } from '@vueuse/core'
import { Brain, Check, ImageOff, Play, Search } from 'lucide-vue-next'
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
    q = q.or(
      `eurio_id.ilike.%${s}%,theme.ilike.%${s}%,country.ilike.${s}`,
    )
  }

  // Apply filters
  if (filterCountry.value) q = q.eq('country', filterCountry.value)
  if (filterFaceValue.value != null) q = q.eq('face_value', filterFaceValue.value)
  if (filterCommemo.value != null) q = q.eq('is_commemorative', filterCommemo.value)
  if (filterNumista.value === 'with') q = q.not('cross_refs->numista_id', 'is', null)
  if (filterNumista.value === 'without') q = q.is('cross_refs->numista_id', null)
  if (filterImages.value === 'with') q = q.neq('images', '[]').not('images', 'is', null)
  if (filterImages.value === 'without') q = q.or('images.eq.[],images.is.null')

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
watch([filterCountry, filterFaceValue, filterCommemo, filterNumista, filterImages], resetAndFetch)
onMounted(() => {
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
  query.value = ''
}

// Training status
const trainedEurioIds = ref<Set<string>>(new Set())

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
  || filterNumista.value != null || filterImages.value != null || query.value

// ─── Training enqueue ───

const ML_API = 'http://localhost:8042'
const mlApiOnline = ref(false)
const selectedDesigns = ref<Set<number>>(new Set())
const enqueueLoading = ref(false)
const enqueueSuccess = ref(false)

async function checkMlApi() {
  try {
    const resp = await fetch(`${ML_API}/health`, { signal: AbortSignal.timeout(3000) })
    mlApiOnline.value = resp.ok
  } catch {
    mlApiOnline.value = false
  }
}

let mlApiInterval: ReturnType<typeof setInterval>

function toggleDesignSelection(numistaId: number, event: Event) {
  event.stopPropagation()
  const s = new Set(selectedDesigns.value)
  if (s.has(numistaId)) s.delete(numistaId)
  else s.add(numistaId)
  selectedDesigns.value = s
}

const selectedCount = computed(() => selectedDesigns.value.size)

async function enqueueSelected() {
  if (!mlApiOnline.value || selectedDesigns.value.size === 0) return
  enqueueLoading.value = true
  try {
    const resp = await fetch(`${ML_API}/train`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ design_ids: Array.from(selectedDesigns.value) }),
    })
    if (resp.ok) {
      enqueueSuccess.value = true
      selectedDesigns.value = new Set()
      setTimeout(() => { enqueueSuccess.value = false }, 3000)
    }
  } catch {
    // ignore
  } finally {
    enqueueLoading.value = false
  }
}

function clearSelection() {
  selectedDesigns.value = new Set()
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
        placeholder="eurio_id, thème, pays (fr, de…)"
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

          <!-- Selection checkbox (only for coins with numista_id, visible on hover or when selected) -->
          <div
            v-if="hasNumistaId(coin) && mlApiOnline"
            class="absolute left-2 top-2 z-10 flex h-5 w-5 items-center justify-center rounded transition-opacity"
            :class="selectedDesigns.has(coin.cross_refs.numista_id!) ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'"
            :style="{
              background: selectedDesigns.has(coin.cross_refs.numista_id!)
                ? 'var(--indigo-700)' : 'rgba(255,255,255,0.9)',
              border: selectedDesigns.has(coin.cross_refs.numista_id!)
                ? 'none' : '1.5px solid var(--surface-3)',
            }"
            @click="toggleDesignSelection(coin.cross_refs.numista_id!, $event)"
          >
            <Check
              v-if="selectedDesigns.has(coin.cross_refs.numista_id!)"
              class="h-3 w-3"
              style="color: white"
            />
          </div>

          <!-- Face value badge -->
          <span
            class="absolute rounded-full px-2 py-0.5 text-[10px] font-mono font-medium"
            :class="hasNumistaId(coin) && mlApiOnline ? 'left-9 top-2' : 'left-2 top-2'"
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

          <!-- Numista badge -->
          <span
            v-if="hasNumistaId(coin)"
            class="absolute bottom-2 left-2 rounded-full px-1.5 py-0.5 text-[9px] font-mono font-medium"
            style="background: #059669; color: white;"
          >
            N{{ coin.cross_refs.numista_id }}
          </span>

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

    <!-- Sticky bottom bar for training enqueue -->
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
                {{ selectedCount }} design{{ selectedCount > 1 ? 's' : '' }} sélectionné{{ selectedCount > 1 ? 's' : '' }}
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
              <span
                v-if="enqueueSuccess"
                class="text-xs font-medium"
                style="color: var(--success)"
              >
                Ajouté à la queue !
              </span>
              <button
                class="flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-all"
                style="background: var(--indigo-700); color: white"
                :disabled="enqueueLoading"
                @click="enqueueSelected"
              >
                <Play class="h-3.5 w-3.5" />
                Ajouter à la queue
              </button>
            </div>
          </div>
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
