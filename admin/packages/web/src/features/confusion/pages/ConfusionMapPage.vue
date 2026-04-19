<script setup lang="ts">
import {
  checkMlApiOnline,
  fetchPairs,
  fetchStats,
  fetchStatus,
  postCompute,
  type ComputeStatus,
  type ConfusionPair,
  type ConfusionStats,
} from '@/features/confusion/composables/useConfusionMap'
import { zoneStyle } from '@/features/confusion/composables/useConfusionZone'
import type { ConfusionZone } from '@/shared/supabase/types'
import {
  AlertTriangle,
  Filter,
  ImageOff,
  Loader2,
  Network,
  RefreshCw,
  Search,
  Wifi,
  WifiOff,
} from 'lucide-vue-next'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

/* ───────── State ───────── */

const mlApiOnline = ref(false)
const mlApiChecking = ref(true)

const stats = ref<ConfusionStats | null>(null)
const statsLoading = ref(true)
const statsError = ref<string | null>(null)

const pairs = ref<ConfusionPair[]>([])
const pairsLoading = ref(true)
const pairsError = ref<string | null>(null)

const computeStatus = ref<ComputeStatus | null>(null)
const computing = ref(false)

// Filters for the pairs section
const filterZone = ref<'all' | ConfusionZone>('all')
const filterCountry = ref<string>('')
const filterQuery = ref<string>('')

const COUNTRIES = [
  'AD', 'AT', 'BE', 'BG', 'CY', 'DE', 'EE', 'ES', 'FI', 'FR',
  'GR', 'HR', 'IE', 'IT', 'LT', 'LU', 'LV', 'MC', 'MT', 'NL',
  'PT', 'SI', 'SK', 'SM', 'VA',
]

/* ───────── Lifecycle ───────── */

let healthInterval: ReturnType<typeof setInterval> | null = null
let pollInterval: ReturnType<typeof setInterval> | null = null

onMounted(async () => {
  await checkApi()
  healthInterval = setInterval(checkApi, 30_000)
  await Promise.all([loadStats(), loadPairs()])
  // Check if a compute is already running (picked up mid-flight)
  if (mlApiOnline.value) {
    await refreshStatus()
    if (computeStatus.value?.running) startPolling()
  }
})

onUnmounted(() => {
  if (healthInterval) clearInterval(healthInterval)
  stopPolling()
})

async function checkApi() {
  mlApiChecking.value = true
  mlApiOnline.value = await checkMlApiOnline()
  mlApiChecking.value = false
}

/* ───────── Data loaders ───────── */

async function loadStats() {
  statsLoading.value = true
  statsError.value = null
  try {
    stats.value = await fetchStats(mlApiOnline.value)
  } catch (e) {
    statsError.value = (e as Error).message
  } finally {
    statsLoading.value = false
  }
}

async function loadPairs() {
  pairsLoading.value = true
  pairsError.value = null
  try {
    pairs.value = await fetchPairs(mlApiOnline.value, {
      limit: 100,
      zone: filterZone.value,
    })
  } catch (e) {
    pairsError.value = (e as Error).message
  } finally {
    pairsLoading.value = false
  }
}

watch(filterZone, () => loadPairs())

/* ───────── Compute + polling ───────── */

async function refreshStatus() {
  try {
    computeStatus.value = await fetchStatus()
  } catch {
    /* silent */
  }
}

async function triggerCompute() {
  if (!mlApiOnline.value || computing.value) return
  computing.value = true
  try {
    await postCompute({ encoder_version: 'dinov2-vits14' })
    await refreshStatus()
    startPolling()
  } catch (e) {
    computing.value = false
    statsError.value = `Lancement échoué : ${(e as Error).message}`
  }
}

function startPolling() {
  if (pollInterval) return
  pollInterval = setInterval(async () => {
    await refreshStatus()
    if (!computeStatus.value?.running) {
      stopPolling()
      computing.value = false
      await Promise.all([loadStats(), loadPairs()])
    }
  }, 1500)
}

function stopPolling() {
  if (pollInterval) {
    clearInterval(pollInterval)
    pollInterval = null
  }
}

/* ───────── Derived / display ───────── */

const totalCoins = computed(() => stats.value?.total ?? 0)

const zonePercents = computed(() => {
  const t = totalCoins.value
  if (!t || !stats.value) return { green: 0, orange: 0, red: 0 }
  const { green, orange, red } = stats.value.by_zone
  return {
    green: (green / t) * 100,
    orange: (orange / t) * 100,
    red: (red / t) * 100,
  }
})

const riskyPercent = computed(() =>
  zonePercents.value.orange + zonePercents.value.red,
)

const maxBinCount = computed(() => {
  if (!stats.value?.histogram_bins?.length) return 1
  return Math.max(1, ...stats.value.histogram_bins.map(b => b.count))
})

function binColor(binStart: number): string {
  if (binStart >= 0.85) return 'var(--danger)'
  if (binStart >= 0.70) return 'var(--warning)'
  return 'var(--success)'
}

function binSoft(binStart: number): string {
  if (binStart >= 0.85) return 'var(--danger-soft)'
  if (binStart >= 0.70) return 'var(--warning-soft)'
  return 'var(--success-soft)'
}

const filteredPairs = computed(() => {
  let list = pairs.value
  if (filterCountry.value) {
    const c = filterCountry.value
    list = list.filter(p => p.coin_a.country === c || p.coin_b.country === c)
  }
  if (filterQuery.value.trim()) {
    const q = filterQuery.value.trim().toLowerCase()
    list = list.filter(p =>
      p.eurio_id_a.toLowerCase().includes(q)
      || p.eurio_id_b.toLowerCase().includes(q)
      || (p.coin_a.theme ?? '').toLowerCase().includes(q)
      || (p.coin_b.theme ?? '').toLowerCase().includes(q),
    )
  }
  return list
})

const hasActiveFilters = computed(
  () => filterCountry.value !== '' || filterQuery.value.trim() !== '',
)

function clearFilters() {
  filterCountry.value = ''
  filterQuery.value = ''
}

function formatSim(s: number): string {
  return s.toFixed(3)
}

function formatFaceValue(v: number): string {
  if (!v) return ''
  if (v >= 1) return `${v.toFixed(0)}€`
  return `${(v * 100).toFixed(0)}¢`
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('fr-FR', {
    day: 'numeric', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

function formatRelativeDate(iso: string | null): string {
  if (!iso) return 'jamais calculé'
  const d = new Date(iso).getTime()
  const now = Date.now()
  const diffMin = Math.floor((now - d) / 60000)
  if (diffMin < 1) return 'à l\'instant'
  if (diffMin < 60) return `il y a ${diffMin} min`
  const diffH = Math.floor(diffMin / 60)
  if (diffH < 24) return `il y a ${diffH} h`
  const diffD = Math.floor(diffH / 24)
  if (diffD < 7) return `il y a ${diffD} j`
  return formatDate(iso)
}

function goPairA(p: ConfusionPair) {
  router.push(`/coins/${encodeURIComponent(p.eurio_id_a)}`)
}

const progressPercent = computed(() => {
  const p = computeStatus.value?.progress
  if (!p || !p.total) return 0
  return Math.min(100, Math.round((p.current / p.total) * 100))
})
</script>

<template>
  <div class="p-8">
    <!-- ═══════════════════════ Header ═══════════════════════ -->
    <header class="mb-8">
      <div class="flex items-start justify-between gap-6">
        <div class="min-w-0 flex-1">
          <p
            class="mb-1 text-[10px] font-medium uppercase"
            style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
          >
            Phase 1 · ML scalability
          </p>
          <h1
            class="font-display text-3xl italic font-semibold leading-tight"
            style="color: var(--indigo-700);"
          >
            Cartographie de confusion
          </h1>
          <p class="mt-1.5 max-w-xl text-sm leading-snug" style="color: var(--ink-500);">
            Distance visuelle entre designs du catalogue — identifie les paires
            quasi-jumelles qui nécessitent un enrichissement avant entraînement.
          </p>
        </div>

        <div class="flex flex-shrink-0 items-center gap-3">
          <!-- ML API status pill -->
          <div
            class="flex items-center gap-2 rounded-full border px-3 py-1.5"
            :style="{
              borderColor: mlApiOnline ? 'var(--success)' : 'var(--surface-3)',
              background: mlApiOnline
                ? 'color-mix(in srgb, var(--success) 8%, var(--surface))'
                : 'var(--surface)',
            }"
          >
            <template v-if="mlApiChecking">
              <Loader2 class="h-3.5 w-3.5 animate-spin" style="color: var(--ink-400);" />
              <span class="text-xs" style="color: var(--ink-400);">Connexion…</span>
            </template>
            <template v-else-if="mlApiOnline">
              <Wifi class="h-3.5 w-3.5" style="color: var(--success);" />
              <span class="text-xs font-medium" style="color: var(--success);">API ML</span>
            </template>
            <template v-else>
              <WifiOff class="h-3.5 w-3.5" style="color: var(--ink-400);" />
              <span class="text-xs" style="color: var(--ink-400);">Lecture seule</span>
            </template>
          </div>

          <!-- Recalc button / progress inline -->
          <div
            v-if="computeStatus?.running"
            class="flex min-w-[260px] items-center gap-3 rounded-md border px-4 py-2"
            style="border-color: var(--indigo-700); background: color-mix(in srgb, var(--indigo-700) 4%, var(--surface));"
          >
            <Loader2 class="h-3.5 w-3.5 animate-spin" style="color: var(--indigo-700);" />
            <div class="min-w-0 flex-1">
              <div class="flex items-baseline justify-between gap-2">
                <span class="text-xs font-medium" style="color: var(--indigo-700);">
                  {{ computeStatus.progress.stage || 'compute' }}
                </span>
                <span class="font-mono text-[10px]" style="color: var(--ink-500);">
                  {{ computeStatus.progress.current }} / {{ computeStatus.progress.total || '?' }}
                </span>
              </div>
              <div class="mt-1 h-1 overflow-hidden rounded-full" style="background: var(--surface-2);">
                <div
                  class="h-full rounded-full transition-all duration-500"
                  :style="{ width: `${progressPercent}%`, background: 'var(--indigo-700)' }"
                />
              </div>
            </div>
          </div>
          <button
            v-else
            class="flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-all"
            :style="{
              background: mlApiOnline ? 'var(--indigo-700)' : 'var(--surface-2)',
              color: mlApiOnline ? 'white' : 'var(--ink-400)',
              cursor: mlApiOnline ? 'pointer' : 'not-allowed',
              boxShadow: mlApiOnline ? 'var(--shadow-sm)' : 'none',
            }"
            :disabled="!mlApiOnline || computing"
            :title="mlApiOnline
              ? 'Relance le calcul DINOv2 sur tout le catalogue'
              : 'API ML hors ligne — lance `go-task api` dans ml/ pour activer'"
            @click="triggerCompute"
          >
            <RefreshCw class="h-3.5 w-3.5" :class="computing ? 'animate-spin' : ''" />
            Recalculer la cartographie
          </button>
        </div>
      </div>

      <!-- Gold hairline (Eurio editorial signature) -->
      <div class="mt-6 h-px w-16" style="background: var(--gold);" />
    </header>

    <!-- ═══════════════════════ Summary (3 stat cards) ═══════════════════════ -->
    <section class="mb-10">
      <!-- Section label -->
      <p
        class="mb-3 text-[10px] font-medium uppercase"
        style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
      >
        Résumé
      </p>

      <div v-if="statsLoading" class="grid grid-cols-1 gap-4 md:grid-cols-[1.3fr_1fr_1fr]">
        <div
          v-for="i in 3" :key="i"
          class="h-36 animate-pulse rounded-lg"
          style="background: var(--surface-1);"
        />
      </div>

      <div
        v-else-if="!stats || totalCoins === 0"
        class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed px-8 py-14 text-center"
        style="border-color: var(--surface-3);"
      >
        <Network class="mb-3 h-8 w-8" style="color: var(--ink-300);" />
        <p class="font-display italic text-lg" style="color: var(--ink);">
          Aucune cartographie disponible
        </p>
        <p class="mt-1.5 max-w-sm text-sm" style="color: var(--ink-500);">
          Lance <span class="font-medium" style="color: var(--indigo-700);">Recalculer</span>
          pour générer la distance visuelle entre tous les designs du catalogue.
          <template v-if="!mlApiOnline">
            Nécessite l'API ML locale
            (<code class="font-mono text-[11px]" style="color: var(--indigo-700);">go-task api</code> dans
            <code class="font-mono text-[11px]" style="color: var(--indigo-700);">ml/</code>).
          </template>
        </p>
      </div>

      <div
        v-else
        class="grid grid-cols-1 gap-4 md:grid-cols-[1.3fr_1fr_1fr]"
      >
        <!-- Card 1 — Meta -->
        <article
          class="relative flex flex-col justify-between overflow-hidden rounded-lg border p-5"
          style="
            border-color: var(--surface-3);
            background: linear-gradient(160deg, var(--surface), var(--surface-1));
            box-shadow: var(--shadow-sm);
          "
        >
          <div>
            <p
              class="text-[10px] font-medium uppercase"
              style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);"
            >
              Catalogue cartographié
            </p>
            <p
              class="mt-2 font-display text-4xl font-semibold tabular-nums leading-none"
              style="color: var(--indigo-700);"
            >
              {{ totalCoins.toLocaleString('fr-FR') }}
              <span class="text-lg italic" style="color: var(--ink-400);">designs</span>
            </p>
          </div>
          <div class="mt-4 flex items-end justify-between gap-3">
            <div>
              <p class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                Dernier calcul
              </p>
              <p class="text-sm" style="color: var(--ink);">
                {{ formatRelativeDate(stats.last_computed_at) }}
              </p>
              <p v-if="stats.last_computed_at" class="font-mono text-[10px]" style="color: var(--ink-400);">
                {{ formatDate(stats.last_computed_at) }}
              </p>
            </div>
            <span
              class="rounded-full px-2 py-0.5 font-mono text-[10px]"
              style="background: var(--surface-2); color: var(--ink-500);"
            >
              {{ stats.encoder_version }}
            </span>
          </div>
        </article>

        <!-- Card 2 — Green -->
        <article
          class="relative flex flex-col justify-between overflow-hidden rounded-lg border p-5"
          style="border-color: var(--surface-3); background: var(--surface); box-shadow: var(--shadow-sm);"
        >
          <div>
            <div class="flex items-center gap-2">
              <span class="h-2 w-2 rounded-full" style="background: var(--success);" />
              <p
                class="text-[10px] font-medium uppercase"
                style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);"
              >
                Zone verte · sûre
              </p>
            </div>
            <div class="mt-3 flex items-baseline gap-2">
              <p
                class="font-display text-4xl font-semibold tabular-nums leading-none"
                style="color: var(--success);"
              >
                {{ zonePercents.green.toFixed(1) }}<span class="text-xl">%</span>
              </p>
              <p class="font-mono text-xs" style="color: var(--ink-400);">
                {{ stats.by_zone.green }} designs
              </p>
            </div>
          </div>
          <div class="mt-4">
            <div class="h-1.5 overflow-hidden rounded-full" style="background: var(--surface-2);">
              <div
                class="h-full rounded-full transition-all duration-700"
                :style="{ width: `${zonePercents.green}%`, background: 'var(--success)' }"
              />
            </div>
            <p class="mt-2 text-[11px] italic" style="color: var(--ink-500);">
              Entraînement direct, Numista + augmentation suffisent.
            </p>
          </div>
        </article>

        <!-- Card 3 — Orange + Red (stacked bar) -->
        <article
          class="relative flex flex-col justify-between overflow-hidden rounded-lg border p-5"
          style="border-color: var(--surface-3); background: var(--surface); box-shadow: var(--shadow-sm);"
        >
          <div>
            <div class="flex items-center gap-2">
              <span class="flex">
                <span class="h-2 w-2 rounded-full" style="background: var(--warning);" />
                <span class="-ml-0.5 h-2 w-2 rounded-full" style="background: var(--danger);" />
              </span>
              <p
                class="text-[10px] font-medium uppercase"
                style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);"
              >
                Zones à risque
              </p>
            </div>
            <div class="mt-3 flex items-baseline gap-2">
              <p
                class="font-display text-4xl font-semibold tabular-nums leading-none"
                style="color: var(--ink);"
              >
                {{ riskyPercent.toFixed(1) }}<span class="text-xl">%</span>
              </p>
              <p class="font-mono text-xs" style="color: var(--ink-400);">
                à surveiller
              </p>
            </div>
          </div>
          <div class="mt-4">
            <!-- Split stacked bar -->
            <div class="flex h-1.5 overflow-hidden rounded-full" style="background: var(--surface-2);">
              <div
                class="h-full transition-all duration-700"
                :style="{ width: `${zonePercents.orange}%`, background: 'var(--warning)' }"
                :title="`${zonePercents.orange.toFixed(1)}% orange`"
              />
              <div
                class="h-full transition-all duration-700"
                :style="{ width: `${zonePercents.red}%`, background: 'var(--danger)' }"
                :title="`${zonePercents.red.toFixed(1)}% rouge`"
              />
            </div>
            <div class="mt-2 flex items-center justify-between font-mono text-[11px]">
              <span style="color: var(--warning);">
                {{ zonePercents.orange.toFixed(1) }}% · {{ stats.by_zone.orange }} orange
              </span>
              <span style="color: var(--danger);">
                {{ zonePercents.red.toFixed(1) }}% · {{ stats.by_zone.red }} rouge
              </span>
            </div>
          </div>
        </article>
      </div>

      <div
        v-if="statsError"
        class="mt-3 rounded-md px-4 py-2 text-xs"
        style="background: var(--danger-soft); color: var(--danger);"
      >
        {{ statsError }}
      </div>
    </section>

    <!-- ═══════════════════════ Histogram ═══════════════════════ -->
    <section v-if="stats && totalCoins > 0" class="mb-10">
      <div class="mb-3 flex items-end justify-between">
        <div>
          <p
            class="text-[10px] font-medium uppercase"
            style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
          >
            Distribution
          </p>
          <h2 class="font-display text-xl italic font-semibold" style="color: var(--indigo-700);">
            Similarité du voisin le plus proche
          </h2>
        </div>
        <!-- Legend -->
        <div class="flex items-center gap-4 text-[11px]" style="color: var(--ink-500);">
          <span class="flex items-center gap-1.5">
            <span class="h-2 w-3 rounded-sm" style="background: var(--success);" />
            &lt; 0.70
          </span>
          <span class="flex items-center gap-1.5">
            <span class="h-2 w-3 rounded-sm" style="background: var(--warning);" />
            0.70 – 0.85
          </span>
          <span class="flex items-center gap-1.5">
            <span class="h-2 w-3 rounded-sm" style="background: var(--danger);" />
            ≥ 0.85
          </span>
        </div>
      </div>

      <div
        class="rounded-lg border p-6"
        style="border-color: var(--surface-3); background: var(--surface); box-shadow: var(--shadow-sm);"
      >
        <!-- Histogram -->
        <div class="relative h-48">
          <!-- Threshold lines -->
          <div
            class="absolute top-0 bottom-0 border-l border-dashed"
            :style="{ left: `${(0.70 / 1.0) * 100}%`, borderColor: 'var(--warning)', opacity: 0.5 }"
          >
            <span
              class="absolute -top-5 -translate-x-1/2 rounded-sm px-1 font-mono text-[9px] font-medium uppercase"
              style="background: var(--warning-soft); color: var(--warning); letter-spacing: 0.05em;"
            >
              0.70
            </span>
          </div>
          <div
            class="absolute top-0 bottom-0 border-l border-dashed"
            :style="{ left: `${(0.85 / 1.0) * 100}%`, borderColor: 'var(--danger)', opacity: 0.5 }"
          >
            <span
              class="absolute -top-5 -translate-x-1/2 rounded-sm px-1 font-mono text-[9px] font-medium uppercase"
              style="background: var(--danger-soft); color: var(--danger); letter-spacing: 0.05em;"
            >
              0.85
            </span>
          </div>

          <!-- Bars -->
          <div class="absolute inset-x-0 bottom-0 top-0 flex items-end gap-px">
            <div
              v-for="(bin, i) in stats.histogram_bins"
              :key="i"
              class="group relative flex-1 transition-all duration-300"
              :style="{
                height: `${(bin.count / maxBinCount) * 100}%`,
                minHeight: bin.count > 0 ? '2px' : '0',
                background: binColor(bin.bin_start),
                borderTop: `1px solid ${binColor(bin.bin_start)}`,
                opacity: bin.count > 0 ? 1 : 0.08,
              }"
            >
              <!-- Hover tooltip -->
              <div
                class="pointer-events-none absolute bottom-full left-1/2 mb-1 -translate-x-1/2 whitespace-nowrap rounded px-1.5 py-0.5 font-mono text-[10px] opacity-0 transition-opacity group-hover:opacity-100"
                style="background: var(--ink); color: white;"
              >
                {{ bin.bin_start.toFixed(2) }}–{{ (bin.bin_start + 0.05).toFixed(2) }} · {{ bin.count }}
              </div>
              <!-- Soft top highlight -->
              <div
                class="absolute inset-x-0 top-0 h-full"
                :style="{
                  background: `linear-gradient(to bottom, ${binSoft(bin.bin_start)}, transparent 40%)`,
                }"
              />
            </div>
          </div>
        </div>

        <!-- X axis -->
        <div
          class="mt-2 flex justify-between border-t pt-2 font-mono text-[10px]"
          style="color: var(--ink-400); border-color: var(--surface-2);"
        >
          <span>0.00</span>
          <span>0.25</span>
          <span>0.50</span>
          <span style="color: var(--warning);">0.70</span>
          <span style="color: var(--danger);">0.85</span>
          <span>1.00</span>
        </div>
      </div>
    </section>

    <!-- ═══════════════════════ Pairs ═══════════════════════ -->
    <section v-if="stats && totalCoins > 0">
      <div class="mb-3 flex items-end justify-between gap-4">
        <div>
          <p
            class="text-[10px] font-medium uppercase"
            style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
          >
            Ledger
          </p>
          <h2 class="font-display text-xl italic font-semibold" style="color: var(--indigo-700);">
            Paires les plus confondues
          </h2>
        </div>
        <p class="pb-1 font-mono text-xs" style="color: var(--ink-400);">
          {{ filteredPairs.length }} / {{ pairs.length }} paires
        </p>
      </div>

      <!-- Filters -->
      <div
        class="mb-5 flex flex-wrap items-center gap-3 rounded-md border p-3"
        style="border-color: var(--surface-3); background: var(--surface);"
      >
        <!-- Zone -->
        <div class="flex items-center gap-2">
          <Filter class="h-3.5 w-3.5" style="color: var(--ink-400);" />
          <span
            class="text-[10px] font-medium uppercase"
            style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);"
          >
            Zone
          </span>
        </div>
        <div class="flex gap-1">
          <button
            v-for="z in (['all', 'red', 'orange', 'green'] as const)" :key="z"
            class="rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors"
            :style="{
              background: filterZone === z
                ? (z === 'all' ? 'var(--indigo-700)' : zoneStyle(z as 'green' | 'orange' | 'red').solid)
                : 'var(--surface)',
              color: filterZone === z ? 'white' : 'var(--ink-500)',
              borderColor: filterZone === z
                ? 'transparent'
                : 'var(--surface-3)',
            }"
            @click="filterZone = z"
          >
            <span v-if="z === 'all'">Toutes</span>
            <span v-else-if="z === 'red'">Rouge</span>
            <span v-else-if="z === 'orange'">Orange</span>
            <span v-else>Verte</span>
          </button>
        </div>

        <div class="h-4 w-px" style="background: var(--surface-3);" />

        <!-- Country -->
        <select
          v-model="filterCountry"
          class="rounded-md border px-2 py-1 text-xs font-mono outline-none focus:ring-2"
          style="border-color: var(--surface-3); background: var(--surface); color: var(--ink); --tw-ring-color: var(--indigo-700);"
        >
          <option value="">Tous pays</option>
          <option v-for="c in COUNTRIES" :key="c" :value="c">{{ c }}</option>
        </select>

        <!-- Search -->
        <div class="relative flex-1 max-w-xs">
          <Search class="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2" style="color: var(--ink-400);" />
          <input
            v-model="filterQuery"
            type="search"
            placeholder="eurio_id, thème…"
            class="w-full rounded-md border py-1 pl-8 pr-2 text-xs outline-none focus:ring-2"
            style="border-color: var(--surface-3); background: var(--surface); color: var(--ink); --tw-ring-color: var(--indigo-700);"
          />
        </div>

        <button
          v-if="hasActiveFilters"
          class="rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors"
          style="background: var(--surface-1); color: var(--ink-500);"
          @click="clearFilters"
        >
          Effacer
        </button>
      </div>

      <!-- Loading -->
      <div v-if="pairsLoading" class="space-y-2">
        <div
          v-for="i in 6" :key="i"
          class="h-20 animate-pulse rounded-md"
          style="background: var(--surface-1);"
        />
      </div>

      <div
        v-else-if="pairsError"
        class="rounded-md px-4 py-3 text-sm"
        style="background: var(--danger-soft); color: var(--danger);"
      >
        <AlertTriangle class="mr-1 inline h-4 w-4" />
        {{ pairsError }}
      </div>

      <div
        v-else-if="filteredPairs.length === 0"
        class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed py-12"
        style="border-color: var(--surface-3);"
      >
        <p class="font-display italic text-base" style="color: var(--ink-400);">
          Aucune paire pour ces filtres
        </p>
      </div>

      <!-- Ledger -->
      <div
        v-else
        class="overflow-hidden rounded-lg border"
        style="border-color: var(--surface-3); background: var(--surface);"
      >
        <div
          v-for="(p, i) in filteredPairs"
          :key="`${p.eurio_id_a}__${p.eurio_id_b}`"
          class="group grid cursor-pointer items-center gap-4 px-5 py-3 transition-colors hover:bg-black/[0.02]"
          style="grid-template-columns: 32px auto 1fr auto; border-top: 1px solid var(--surface-2);"
          :style="i === 0 ? 'border-top: none' : ''"
          @click="goPairA(p)"
        >
          <!-- Rank -->
          <span class="font-mono text-[11px] tabular-nums" style="color: var(--ink-300);">
            #{{ (i + 1).toString().padStart(3, '0') }}
          </span>

          <!-- Thumbnails A ↔ B -->
          <div class="flex items-center gap-2">
            <div
              class="relative flex h-14 w-14 flex-shrink-0 items-center justify-center overflow-hidden rounded-md"
              style="background: var(--surface-1);"
            >
              <img
                v-if="p.coin_a.image_url"
                :src="p.coin_a.image_url"
                :alt="p.coin_a.theme ?? p.eurio_id_a"
                class="h-full w-full object-contain p-1"
                loading="lazy"
              />
              <ImageOff v-else class="h-4 w-4" style="color: var(--ink-300);" />
            </div>

            <!-- Similarity bridge -->
            <div class="flex flex-col items-center gap-0.5" style="min-width: 64px;">
              <span
                class="font-mono text-sm font-semibold tabular-nums leading-none"
                :style="{ color: zoneStyle(p.zone).solid }"
              >
                {{ formatSim(p.similarity) }}
              </span>
              <div class="relative h-px w-full" style="background: var(--surface-3);">
                <div
                  class="absolute inset-y-0 left-0"
                  :style="{
                    width: `${Math.min(100, p.similarity * 100)}%`,
                    background: zoneStyle(p.zone).solid,
                    height: '1.5px',
                    top: '-0.25px',
                  }"
                />
              </div>
              <span
                class="font-mono text-[9px] uppercase"
                style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
              >
                cosine
              </span>
            </div>

            <div
              class="relative flex h-14 w-14 flex-shrink-0 items-center justify-center overflow-hidden rounded-md"
              style="background: var(--surface-1);"
            >
              <img
                v-if="p.coin_b.image_url"
                :src="p.coin_b.image_url"
                :alt="p.coin_b.theme ?? p.eurio_id_b"
                class="h-full w-full object-contain p-1"
                loading="lazy"
              />
              <ImageOff v-else class="h-4 w-4" style="color: var(--ink-300);" />
            </div>
          </div>

          <!-- Meta -->
          <div class="min-w-0 grid grid-cols-2 gap-4">
            <div class="min-w-0">
              <div class="flex items-center gap-1.5">
                <span class="font-mono text-[10px] uppercase" style="color: var(--ink-400);">
                  {{ p.coin_a.country }}
                </span>
                <span v-if="p.coin_a.year" class="font-mono text-[10px]" style="color: var(--ink-400);">
                  {{ p.coin_a.year }}
                </span>
                <span
                  v-if="p.coin_a.face_value"
                  class="rounded-full px-1.5 font-mono text-[9px]"
                  style="background: var(--surface-2); color: var(--ink-500);"
                >
                  {{ formatFaceValue(p.coin_a.face_value) }}
                </span>
              </div>
              <p class="mt-0.5 truncate text-xs" style="color: var(--ink);">
                {{ p.coin_a.theme ?? p.eurio_id_a }}
              </p>
              <p class="truncate font-mono text-[10px]" style="color: var(--ink-300);">
                {{ p.eurio_id_a }}
              </p>
            </div>
            <div class="min-w-0">
              <div class="flex items-center gap-1.5">
                <span class="font-mono text-[10px] uppercase" style="color: var(--ink-400);">
                  {{ p.coin_b.country }}
                </span>
                <span v-if="p.coin_b.year" class="font-mono text-[10px]" style="color: var(--ink-400);">
                  {{ p.coin_b.year }}
                </span>
                <span
                  v-if="p.coin_b.face_value"
                  class="rounded-full px-1.5 font-mono text-[9px]"
                  style="background: var(--surface-2); color: var(--ink-500);"
                >
                  {{ formatFaceValue(p.coin_b.face_value) }}
                </span>
              </div>
              <p class="mt-0.5 truncate text-xs" style="color: var(--ink);">
                {{ p.coin_b.theme ?? p.eurio_id_b }}
              </p>
              <p class="truncate font-mono text-[10px]" style="color: var(--ink-300);">
                {{ p.eurio_id_b }}
              </p>
            </div>
          </div>

          <!-- Zone badge -->
          <span
            class="flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-medium uppercase"
            :style="{
              background: zoneStyle(p.zone).soft,
              color: zoneStyle(p.zone).solid,
              letterSpacing: 'var(--tracking-eyebrow)',
            }"
          >
            <span class="h-1.5 w-1.5 rounded-full" :style="{ background: zoneStyle(p.zone).solid }" />
            {{ p.zone }}
          </span>
        </div>
      </div>
    </section>
  </div>
</template>
