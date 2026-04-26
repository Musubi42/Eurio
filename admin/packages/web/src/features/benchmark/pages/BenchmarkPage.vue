<script setup lang="ts">
import { checkMlApi } from '@/features/training/composables/useTrainingApi'
import {
  deleteBenchmarkRun,
  fetchBenchmarkRuns,
  fetchLibrary,
  postBenchmarkRun,
} from '@/features/benchmark/composables/useBenchmarkApi'
import type { BenchmarkLibrary, BenchmarkRunSummary } from '@/features/benchmark/types'
import {
  Camera,
  Filter,
  Loader2,
  Play,
  RefreshCw,
  Trash2,
  TrendingUp,
  Wifi,
  WifiOff,
  X,
} from 'lucide-vue-next'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

/* ───────── State ───────── */

const mlApiOnline = ref(false)
const mlApiChecking = ref(true)

const library = ref<BenchmarkLibrary | null>(null)
const libraryLoading = ref(true)
const libraryError = ref<string | null>(null)

const runs = ref<BenchmarkRunSummary[]>([])
const total = ref(0)
const runsLoading = ref(true)
const runsError = ref<string | null>(null)

const filterModel = ref<string>('')
const filterZone = ref<'' | 'green' | 'orange' | 'red'>('')

const compareSelection = ref<Set<string>>(new Set())
const compareMode = ref(false)

const showNewRunModal = ref(false)
const newRunPayload = ref({
  model_path: 'ml/checkpoints/best_model.pth',
  zones: [] as string[],
})
const newRunSubmitting = ref(false)
const newRunError = ref<string | null>(null)

/* ───────── Lifecycle ───────── */

let healthInterval: ReturnType<typeof setInterval> | null = null
let pollInterval: ReturnType<typeof setInterval> | null = null

onMounted(async () => {
  await checkApi()
  healthInterval = setInterval(checkApi, 30_000)
  await Promise.all([loadLibrary(), loadRuns()])
  if (runs.value.some(r => r.status === 'running')) startPolling()
})

onUnmounted(() => {
  if (healthInterval) clearInterval(healthInterval)
  if (pollInterval) clearInterval(pollInterval)
})

async function checkApi() {
  mlApiChecking.value = true
  mlApiOnline.value = await checkMlApi()
  mlApiChecking.value = false
}

async function loadLibrary() {
  libraryLoading.value = true
  libraryError.value = null
  try {
    library.value = await fetchLibrary()
  } catch (e) {
    libraryError.value = (e as Error).message
  } finally {
    libraryLoading.value = false
  }
}

async function loadRuns() {
  runsLoading.value = true
  runsError.value = null
  try {
    const data = await fetchBenchmarkRuns({
      model_name: filterModel.value || undefined,
      zone: filterZone.value || undefined,
      limit: 100,
    })
    runs.value = data.items
    total.value = data.total
  } catch (e) {
    runsError.value = (e as Error).message
  } finally {
    runsLoading.value = false
  }
}

watch([filterModel, filterZone], () => loadRuns())

function startPolling() {
  if (pollInterval) return
  pollInterval = setInterval(async () => {
    await loadRuns()
    if (!runs.value.some(r => r.status === 'running')) {
      clearInterval(pollInterval!)
      pollInterval = null
    }
  }, 2500)
}

/* ───────── Compare ───────── */

function toggleCompare() {
  compareMode.value = !compareMode.value
  if (!compareMode.value) compareSelection.value = new Set()
}

function toggleSelectRun(id: string) {
  const next = new Set(compareSelection.value)
  if (next.has(id)) next.delete(id)
  else if (next.size < 2) next.add(id)
  compareSelection.value = next
}

function goCompare() {
  const ids = Array.from(compareSelection.value)
  if (ids.length !== 2) return
  router.push(`/benchmark/compare?a=${ids[0]}&b=${ids[1]}`)
}

/* ───────── New run ───────── */

function openNewRun() {
  showNewRunModal.value = true
  newRunPayload.value = {
    model_path: 'ml/checkpoints/best_model.pth',
    zones: [],
  }
  newRunError.value = null
}

function toggleZoneInPayload(z: string) {
  const zones = newRunPayload.value.zones
  const i = zones.indexOf(z)
  if (i >= 0) zones.splice(i, 1)
  else zones.push(z)
}

async function submitNewRun() {
  newRunSubmitting.value = true
  newRunError.value = null
  try {
    await postBenchmarkRun({
      model_path: newRunPayload.value.model_path,
      zones: newRunPayload.value.zones.length ? newRunPayload.value.zones : undefined,
    })
    showNewRunModal.value = false
    await loadRuns()
    startPolling()
  } catch (e) {
    newRunError.value = (e as Error).message
  } finally {
    newRunSubmitting.value = false
  }
}

async function handleDelete(run: BenchmarkRunSummary) {
  const ok = confirm(`Supprimer le run ${run.model_name} du ${formatDate(run.started_at)} ?`)
  if (!ok) return
  try {
    await deleteBenchmarkRun(run.id)
    await loadRuns()
  } catch (e) {
    alert(`Suppression échouée : ${(e as Error).message}`)
  }
}

/* ───────── Formatters ───────── */

function formatPct(v: number | null): string {
  if (v == null) return '—'
  return `${(v * 100).toFixed(1)}%`
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('fr-FR', {
    day: 'numeric', month: 'short',
    hour: '2-digit', minute: '2-digit',
  })
}

function statusStyle(status: string) {
  if (status === 'running') return { bg: 'color-mix(in srgb, var(--indigo-700) 12%, var(--surface))', fg: 'var(--indigo-700)' }
  if (status === 'failed') return { bg: 'color-mix(in srgb, var(--danger) 12%, var(--surface))', fg: 'var(--danger)' }
  return { bg: 'color-mix(in srgb, var(--success) 12%, var(--surface))', fg: 'var(--success)' }
}

function zoneColor(zone: string): string {
  if (zone === 'green') return 'var(--success)'
  if (zone === 'orange') return 'var(--warning)'
  if (zone === 'red') return 'var(--danger)'
  return 'var(--ink-400)'
}

const compareDisabled = computed(() => compareSelection.value.size !== 2)
</script>

<template>
  <div class="p-8">
    <!-- Header -->
    <header class="mb-8">
      <div class="flex items-start justify-between gap-6">
        <div class="min-w-0 flex-1">
          <p
            class="mb-1 text-[10px] font-medium uppercase"
            style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
          >
            Phase 2 · ML scalability · PRD Bloc 3
          </p>
          <h1
            class="font-display text-3xl italic font-semibold leading-tight"
            style="color: var(--indigo-700);"
          >
            Benchmark — Real-Photo Hold-out
          </h1>
          <p class="mt-1.5 max-w-xl text-sm leading-snug" style="color: var(--ink-500);">
            Le dyno du pipeline d'augmentation. Évalue chaque modèle ArcFace sur tes
            photos réelles (strict hold-out) pour trancher quelle recette gagne.
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

          <button
            class="flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-all"
            :style="{
              background: mlApiOnline ? 'var(--indigo-700)' : 'var(--surface-2)',
              color: mlApiOnline ? 'white' : 'var(--ink-400)',
              cursor: mlApiOnline ? 'pointer' : 'not-allowed',
              boxShadow: mlApiOnline ? 'var(--shadow-sm)' : 'none',
            }"
            :disabled="!mlApiOnline"
            :title="mlApiOnline
              ? 'Lance un nouveau run de benchmark'
              : 'API ML hors ligne — lance `go-task ml:api` pour activer'"
            @click="openNewRun"
          >
            <Play class="h-3.5 w-3.5" />
            Nouveau run
          </button>
        </div>
      </div>

      <div class="mt-6 h-px w-16" style="background: var(--gold);" />
    </header>

    <!-- Offline banner -->
    <div
      v-if="!mlApiChecking && !mlApiOnline"
      class="mb-8 rounded-md border px-4 py-3 text-sm"
      style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 6%, var(--surface)); color: var(--ink);"
    >
      L'API ML locale est hors ligne. Les runs historiques ne sont pas consultables.
      Démarre-la avec
      <code class="font-mono text-[12px]" style="color: var(--indigo-700);">go-task ml:api</code>
      dans <code class="font-mono text-[12px]" style="color: var(--indigo-700);">ml/</code>.
    </div>

    <!-- Library summary -->
    <section class="mb-10">
      <p
        class="mb-3 text-[10px] font-medium uppercase"
        style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
      >
        Bibliothèque
      </p>

      <div
        v-if="libraryLoading"
        class="h-24 animate-pulse rounded-lg"
        style="background: var(--surface-1);"
      />

      <div
        v-else-if="!library?.available"
        class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed px-8 py-10 text-center"
        style="border-color: var(--surface-3);"
      >
        <Camera class="mb-3 h-8 w-8" style="color: var(--ink-300);" />
        <p class="font-display italic text-lg" style="color: var(--ink);">
          Pas encore de photos réelles
        </p>
        <p class="mt-1.5 max-w-md text-sm" style="color: var(--ink-500);">
          Dépose tes JPG/PNG dans
          <code class="font-mono text-[11px]" style="color: var(--indigo-700);">ml/data/real_photos/&lt;eurio_id&gt;/</code>
          puis lance
          <code class="font-mono text-[11px]" style="color: var(--indigo-700);">go-task ml:benchmark:photos:check</code>.
          Détails dans <span class="italic">real-photo-criteria.md</span>.
        </p>
      </div>

      <article
        v-else
        class="rounded-lg border px-5 py-4"
        style="border-color: var(--surface-3); background: var(--surface); box-shadow: var(--shadow-sm);"
      >
        <div class="flex items-center justify-between gap-6">
          <div class="flex items-baseline gap-6">
            <div>
              <p
                class="text-[10px] font-medium uppercase"
                style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);"
              >
                Pièces couvertes
              </p>
              <p class="font-display text-2xl tabular-nums leading-none" style="color: var(--indigo-700);">
                {{ library.num_coins }}
              </p>
            </div>
            <div>
              <p
                class="text-[10px] font-medium uppercase"
                style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);"
              >
                Photos
              </p>
              <p class="font-display text-2xl tabular-nums leading-none" style="color: var(--indigo-700);">
                {{ library.num_photos }}
              </p>
            </div>
          </div>
          <div class="flex items-center gap-3">
            <div
              v-for="(count, zone) in library.by_zone"
              :key="zone"
              class="flex items-center gap-1.5 rounded-full px-2.5 py-1"
              :style="{
                background: `color-mix(in srgb, ${zoneColor(zone)} 10%, var(--surface))`,
                color: zoneColor(zone),
              }"
            >
              <span class="h-1.5 w-1.5 rounded-full" :style="{ background: zoneColor(zone) }" />
              <span class="text-xs font-medium">{{ zone }}</span>
              <span class="font-mono text-xs">{{ count }}</span>
            </div>
          </div>
        </div>
      </article>
    </section>

    <!-- Runs table -->
    <section>
      <div class="mb-4 flex items-center justify-between">
        <p
          class="text-[10px] font-medium uppercase"
          style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
        >
          Historique · {{ total }} run{{ total !== 1 ? 's' : '' }}
        </p>
        <div class="flex items-center gap-3">
          <div class="flex items-center gap-2">
            <Filter class="h-3.5 w-3.5" style="color: var(--ink-400);" />
            <input
              v-model="filterModel"
              type="text"
              placeholder="filtrer par modèle"
              class="w-48 rounded-md border px-2.5 py-1 text-xs"
              style="border-color: var(--surface-3);"
            />
            <select
              v-model="filterZone"
              class="rounded-md border px-2 py-1 text-xs"
              style="border-color: var(--surface-3);"
            >
              <option value="">toutes zones</option>
              <option value="green">green</option>
              <option value="orange">orange</option>
              <option value="red">red</option>
            </select>
          </div>
          <button
            class="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium transition-all"
            :style="{
              borderColor: compareMode ? 'var(--indigo-700)' : 'var(--surface-3)',
              color: compareMode ? 'var(--indigo-700)' : 'var(--ink)',
              background: compareMode ? 'color-mix(in srgb, var(--indigo-700) 6%, var(--surface))' : 'var(--surface)',
            }"
            @click="toggleCompare"
          >
            <TrendingUp class="h-3.5 w-3.5" />
            Compare
          </button>
          <button
            v-if="compareMode"
            :disabled="compareDisabled"
            class="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-all"
            :style="{
              background: compareDisabled ? 'var(--surface-2)' : 'var(--indigo-700)',
              color: compareDisabled ? 'var(--ink-400)' : 'white',
              cursor: compareDisabled ? 'not-allowed' : 'pointer',
            }"
            @click="goCompare"
          >
            Comparer ({{ compareSelection.size }}/2)
          </button>
          <button
            class="flex items-center gap-1 rounded-md border px-2.5 py-1.5 text-xs"
            style="border-color: var(--surface-3); color: var(--ink);"
            @click="loadRuns"
          >
            <RefreshCw class="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div
        v-if="runsLoading"
        class="h-48 animate-pulse rounded-lg"
        style="background: var(--surface-1);"
      />
      <div
        v-else-if="runsError"
        class="rounded-md border px-4 py-3 text-sm"
        style="border-color: var(--danger); color: var(--ink);"
      >
        {{ runsError }}
      </div>
      <div
        v-else-if="runs.length === 0"
        class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed px-8 py-12 text-center"
        style="border-color: var(--surface-3);"
      >
        <p class="font-display italic text-lg" style="color: var(--ink);">
          Aucun run pour l'instant
        </p>
        <p class="mt-1 text-sm" style="color: var(--ink-500);">
          Clique <span class="font-medium" style="color: var(--indigo-700);">Nouveau run</span>
          pour évaluer un modèle sur la bibliothèque.
        </p>
      </div>
      <div
        v-else
        class="overflow-hidden rounded-lg border"
        style="border-color: var(--surface-3); background: var(--surface);"
      >
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b" style="border-color: var(--surface-3); background: var(--surface-1);">
              <th v-if="compareMode" class="w-10 px-3 py-2"></th>
              <th class="px-4 py-2 text-left text-[10px] font-medium uppercase" style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">Modèle</th>
              <th class="px-4 py-2 text-left text-[10px] font-medium uppercase" style="color: var(--ink-500);">Recette</th>
              <th class="px-4 py-2 text-right text-[10px] font-medium uppercase" style="color: var(--ink-500);">R@1</th>
              <th class="px-4 py-2 text-right text-[10px] font-medium uppercase" style="color: var(--ink-500);">R@3</th>
              <th class="px-4 py-2 text-right text-[10px] font-medium uppercase" style="color: var(--ink-500);">R@5</th>
              <th class="px-4 py-2 text-right text-[10px] font-medium uppercase" style="color: var(--ink-500);">Photos</th>
              <th class="px-4 py-2 text-left text-[10px] font-medium uppercase" style="color: var(--ink-500);">Zones</th>
              <th class="px-4 py-2 text-left text-[10px] font-medium uppercase" style="color: var(--ink-500);">Date</th>
              <th class="px-4 py-2 text-left text-[10px] font-medium uppercase" style="color: var(--ink-500);">Statut</th>
              <th class="w-10"></th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="run in runs"
              :key="run.id"
              class="cursor-pointer border-b transition-colors hover:bg-[color-mix(in_srgb,var(--indigo-700)_3%,var(--surface))]"
              style="border-color: var(--surface-3);"
              @click.stop="compareMode ? toggleSelectRun(run.id) : router.push(`/benchmark/runs/${run.id}`)"
            >
              <td v-if="compareMode" class="px-3 py-2">
                <input
                  type="checkbox"
                  :checked="compareSelection.has(run.id)"
                  :disabled="!compareSelection.has(run.id) && compareSelection.size >= 2"
                  @click.stop
                  @change="toggleSelectRun(run.id)"
                />
              </td>
              <td class="px-4 py-2">
                <div class="font-medium" style="color: var(--ink);">{{ run.model_name }}</div>
                <div class="font-mono text-[10px]" style="color: var(--ink-400);">{{ run.id }}</div>
              </td>
              <td class="px-4 py-2" style="color: var(--ink-500);">
                {{ run.recipe_id || '—' }}
              </td>
              <td class="px-4 py-2 text-right font-mono tabular-nums" style="color: var(--indigo-700);">
                {{ formatPct(run.r_at_1) }}
              </td>
              <td class="px-4 py-2 text-right font-mono tabular-nums" style="color: var(--ink);">
                {{ formatPct(run.r_at_3) }}
              </td>
              <td class="px-4 py-2 text-right font-mono tabular-nums" style="color: var(--ink);">
                {{ formatPct(run.r_at_5) }}
              </td>
              <td class="px-4 py-2 text-right font-mono tabular-nums" style="color: var(--ink);">
                {{ run.num_photos }}
              </td>
              <td class="px-4 py-2">
                <div class="flex flex-wrap gap-1">
                  <span
                    v-for="z in run.zones"
                    :key="z"
                    class="rounded-full px-2 py-0.5 text-[10px] font-medium"
                    :style="{
                      background: `color-mix(in srgb, ${zoneColor(z)} 15%, var(--surface))`,
                      color: zoneColor(z),
                    }"
                  >
                    {{ z }}
                  </span>
                  <span v-if="run.zones.length === 0" class="text-[10px]" style="color: var(--ink-400);">—</span>
                </div>
              </td>
              <td class="px-4 py-2 text-xs" style="color: var(--ink-500);">
                {{ formatDate(run.started_at) }}
              </td>
              <td class="px-4 py-2">
                <span
                  class="rounded-full px-2 py-0.5 text-[10px] font-medium"
                  :style="{
                    background: statusStyle(run.status).bg,
                    color: statusStyle(run.status).fg,
                  }"
                >
                  {{ run.status }}
                </span>
              </td>
              <td class="px-3 py-2 text-right">
                <button
                  class="rounded p-1 transition-colors hover:bg-[var(--surface-2)]"
                  title="Supprimer"
                  @click.stop="handleDelete(run)"
                >
                  <Trash2 class="h-3.5 w-3.5" style="color: var(--ink-400);" />
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- New run modal -->
    <Teleport to="body">
      <div
        v-if="showNewRunModal"
        class="fixed inset-0 z-50 flex items-center justify-center p-6"
        style="background: rgba(0,0,0,0.4);"
        @click.self="showNewRunModal = false"
      >
        <div
          class="w-full max-w-md rounded-lg border p-6"
          style="border-color: var(--surface-3); background: var(--surface); box-shadow: var(--shadow-card);"
        >
          <div class="mb-4 flex items-start justify-between">
            <div>
              <h2 class="font-display text-xl italic" style="color: var(--indigo-700);">
                Nouveau run
              </h2>
              <p class="mt-1 text-xs" style="color: var(--ink-500);">
                Évalue un checkpoint contre les photos réelles.
              </p>
            </div>
            <button
              class="rounded p-1 transition-colors hover:bg-[var(--surface-2)]"
              @click="showNewRunModal = false"
            >
              <X class="h-4 w-4" style="color: var(--ink-400);" />
            </button>
          </div>

          <label class="block">
            <span class="mb-1 block text-[10px] font-medium uppercase" style="color: var(--ink-500);">
              Chemin modèle (.pth/.pt/.tflite)
            </span>
            <input
              v-model="newRunPayload.model_path"
              type="text"
              class="w-full rounded-md border px-3 py-2 text-sm font-mono"
              style="border-color: var(--surface-3);"
            />
          </label>

          <div class="mt-4">
            <p class="mb-2 text-[10px] font-medium uppercase" style="color: var(--ink-500);">
              Zones (optionnel — toutes si vide)
            </p>
            <div class="flex gap-2">
              <button
                v-for="z in ['green', 'orange', 'red']"
                :key="z"
                class="rounded-full px-3 py-1 text-xs font-medium transition-all"
                :style="{
                  background: newRunPayload.zones.includes(z)
                    ? `color-mix(in srgb, ${zoneColor(z)} 20%, var(--surface))`
                    : 'var(--surface-1)',
                  color: newRunPayload.zones.includes(z) ? zoneColor(z) : 'var(--ink-500)',
                  border: `1px solid ${newRunPayload.zones.includes(z) ? zoneColor(z) : 'var(--surface-3)'}`,
                }"
                @click="toggleZoneInPayload(z)"
              >
                {{ z }}
              </button>
            </div>
          </div>

          <div
            v-if="newRunError"
            class="mt-4 rounded-md border px-3 py-2 text-xs"
            style="border-color: var(--danger); color: var(--danger);"
          >
            {{ newRunError }}
          </div>

          <div class="mt-6 flex justify-end gap-2">
            <button
              class="rounded-md border px-4 py-2 text-sm"
              style="border-color: var(--surface-3); color: var(--ink);"
              @click="showNewRunModal = false"
            >
              Annuler
            </button>
            <button
              :disabled="newRunSubmitting || !newRunPayload.model_path"
              class="flex items-center gap-1.5 rounded-md px-4 py-2 text-sm font-medium"
              :style="{
                background: newRunSubmitting ? 'var(--surface-2)' : 'var(--indigo-700)',
                color: newRunSubmitting ? 'var(--ink-400)' : 'white',
                cursor: newRunSubmitting ? 'wait' : 'pointer',
              }"
              @click="submitNewRun"
            >
              <Loader2 v-if="newRunSubmitting" class="h-3.5 w-3.5 animate-spin" />
              <Play v-else class="h-3.5 w-3.5" />
              Lancer
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
