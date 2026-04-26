<script setup lang="ts">
import { checkMlApi } from '@/features/training/composables/useTrainingApi'
import CohortCard from '@/features/lab/components/CohortCard.vue'
import { fetchCohorts, fetchRunnerStatus } from '@/features/lab/composables/useLabApi'
import type { CohortSummary } from '@/features/lab/types'
import { FlaskConical, Loader2, Plus, Wifi, WifiOff } from 'lucide-vue-next'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

const mlApiOnline = ref(false)
const mlApiChecking = ref(true)
const runnerBusy = ref(false)

const cohorts = ref<CohortSummary[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

const filterZone = ref<'' | 'green' | 'orange' | 'red'>('')

let healthInterval: ReturnType<typeof setInterval> | null = null
let runnerInterval: ReturnType<typeof setInterval> | null = null

onMounted(async () => {
  await checkApi()
  healthInterval = setInterval(checkApi, 30_000)
  runnerInterval = setInterval(refreshRunner, 5_000)
  await Promise.all([load(), refreshRunner()])
})

onUnmounted(() => {
  if (healthInterval) clearInterval(healthInterval)
  if (runnerInterval) clearInterval(runnerInterval)
})

async function checkApi() {
  mlApiChecking.value = true
  mlApiOnline.value = await checkMlApi()
  mlApiChecking.value = false
}

async function refreshRunner() {
  if (!mlApiOnline.value) {
    runnerBusy.value = false
    return
  }
  try {
    const s = await fetchRunnerStatus()
    runnerBusy.value = s.busy
  } catch {
    runnerBusy.value = false
  }
}

async function load() {
  loading.value = true
  error.value = null
  try {
    cohorts.value = await fetchCohorts(filterZone.value || undefined)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

watch(filterZone, load)

function openCohort(c: CohortSummary) {
  router.push(`/lab/cohorts/${c.id}`)
}

const totals = computed(() => ({
  cohorts: cohorts.value.length,
  iterations: cohorts.value.reduce((sum, c) => sum + c.iteration_count, 0),
  bestR1: cohorts.value.reduce<number | null>((best, c) => {
    if (c.best_r_at_1 == null) return best
    if (best == null) return c.best_r_at_1
    return Math.max(best, c.best_r_at_1)
  }, null),
}))

function formatPct(v: number | null): string {
  return v == null ? '—' : `${(v * 100).toFixed(1)}%`
}
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
            Phase 2 · ML scalability · PRD Bloc 4
          </p>
          <h1
            class="font-display text-3xl italic font-semibold leading-tight"
            style="color: var(--indigo-700);"
          >
            Lab — Expériences
          </h1>
          <p class="mt-1.5 max-w-xl text-sm leading-snug" style="color: var(--ink-500);">
            Chaque cohort est une piste de test figée. Tu lances des itérations
            dessus, tu observes les verdicts, tu comprends quels leviers bougent
            la précision.
          </p>
        </div>

        <div class="flex flex-shrink-0 items-center gap-3">
          <div
            class="flex items-center gap-2 rounded-full border px-3 py-1.5"
            :style="{
              borderColor: runnerBusy ? 'var(--warning)' : (mlApiOnline ? 'var(--success)' : 'var(--surface-3)'),
              background: runnerBusy
                ? 'color-mix(in srgb, var(--warning) 10%, var(--surface))'
                : (mlApiOnline ? 'color-mix(in srgb, var(--success) 8%, var(--surface))' : 'var(--surface)'),
            }"
          >
            <template v-if="mlApiChecking">
              <Loader2 class="h-3.5 w-3.5 animate-spin" style="color: var(--ink-400);" />
              <span class="text-xs" style="color: var(--ink-400);">Connexion…</span>
            </template>
            <template v-else-if="runnerBusy">
              <Loader2 class="h-3.5 w-3.5 animate-spin" style="color: var(--warning);" />
              <span class="text-xs font-medium" style="color: var(--warning);">Itération en cours</span>
            </template>
            <template v-else-if="mlApiOnline">
              <Wifi class="h-3.5 w-3.5" style="color: var(--success);" />
              <span class="text-xs font-medium" style="color: var(--success);">API ML prête</span>
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
            @click="router.push('/lab/cohorts/new')"
          >
            <Plus class="h-3.5 w-3.5" />
            Nouveau cohort
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
      L'API ML locale est hors ligne. Lance
      <code class="font-mono text-[12px]" style="color: var(--indigo-700);">go-task ml:api</code>
      pour reprendre.
    </div>

    <!-- Summary strip -->
    <section class="mb-10 grid grid-cols-3 gap-4">
      <article
        v-for="{ label, value, tint } in [
          { label: 'Cohorts', value: String(totals.cohorts), tint: 'var(--indigo-700)' },
          { label: 'Itérations', value: String(totals.iterations), tint: 'var(--ink)' },
          { label: 'Meilleur R@1', value: formatPct(totals.bestR1), tint: totals.bestR1 != null ? 'var(--success)' : 'var(--ink-400)' },
        ]"
        :key="label"
        class="rounded-lg border p-4"
        style="border-color: var(--surface-3); background: var(--surface); box-shadow: var(--shadow-sm);"
      >
        <p class="text-[10px] font-medium uppercase" style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
          {{ label }}
        </p>
        <p class="mt-1 font-display text-3xl font-semibold tabular-nums leading-none" :style="{ color: tint }">
          {{ value }}
        </p>
      </article>
    </section>

    <!-- Filter + list -->
    <section>
      <div class="mb-4 flex items-center justify-between">
        <p class="text-[10px] font-medium uppercase" style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);">
          Cohorts
        </p>
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

      <div v-if="loading" class="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        <div v-for="i in 3" :key="i" class="h-36 animate-pulse rounded-lg" style="background: var(--surface-1);" />
      </div>
      <div
        v-else-if="error"
        class="rounded-md border px-4 py-3 text-sm"
        style="border-color: var(--danger); color: var(--ink);"
      >
        {{ error }}
      </div>
      <div
        v-else-if="cohorts.length === 0"
        class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed px-8 py-12 text-center"
        style="border-color: var(--surface-3);"
      >
        <FlaskConical class="mb-3 h-8 w-8" style="color: var(--ink-300);" />
        <p class="font-display italic text-lg" style="color: var(--ink);">
          Pas encore de cohort
        </p>
        <p class="mt-1 max-w-md text-sm" style="color: var(--ink-500);">
          Un cohort = un ensemble figé de pièces avec leurs photos réelles. Groupe
          3-10 pièces qui partagent un challenge (zone, pays, décennie) et itère dessus.
        </p>
      </div>
      <div v-else class="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        <div v-for="c in cohorts" :key="c.id" @click="openCohort(c)">
          <CohortCard :cohort="c" />
        </div>
      </div>
    </section>
  </div>
</template>
