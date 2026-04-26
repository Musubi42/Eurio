<script setup lang="ts">
import IterationRow from '@/features/lab/components/IterationRow.vue'
import SensitivityPanel from '@/features/lab/components/SensitivityPanel.vue'
import TrajectoryChart from '@/features/lab/components/TrajectoryChart.vue'
import {
  deleteCohort,
  fetchCohort,
  fetchIterations,
  fetchSensitivity,
  fetchTrajectory,
  fetchRunnerStatus,
} from '@/features/lab/composables/useLabApi'
import type {
  CohortSummary,
  IterationDetail,
  SensitivityEntry,
  TrajectoryPoint,
} from '@/features/lab/types'
import { ArrowLeft, Loader2, Plus, Trash2 } from 'lucide-vue-next'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const cohortId = computed(() => String(route.params.id))

const cohort = ref<CohortSummary | null>(null)
const iterations = ref<IterationDetail[]>([])
const trajectory = ref<TrajectoryPoint[]>([])
const sensitivity = ref<SensitivityEntry[]>([])
const runnerBusy = ref(false)

const loading = ref(true)
const error = ref<string | null>(null)

let pollInterval: ReturnType<typeof setInterval> | null = null

onMounted(async () => {
  await reload()
  pollInterval = setInterval(() => {
    // Only poll actively when an iteration is in progress
    if (iterations.value.some(it => it.status === 'training' || it.status === 'benchmarking')) {
      reload()
    } else {
      refreshRunner()
    }
  }, 4000)
})

onUnmounted(() => {
  if (pollInterval) clearInterval(pollInterval)
})

async function reload() {
  loading.value = true
  error.value = null
  try {
    const [c, its, traj, sens, runner] = await Promise.all([
      fetchCohort(cohortId.value),
      fetchIterations(cohortId.value),
      fetchTrajectory(cohortId.value),
      fetchSensitivity(cohortId.value),
      fetchRunnerStatus().catch(() => ({ busy: false })),
    ])
    cohort.value = c
    iterations.value = its
    trajectory.value = traj
    sensitivity.value = sens
    runnerBusy.value = runner.busy
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

async function refreshRunner() {
  try {
    const s = await fetchRunnerStatus()
    runnerBusy.value = s.busy
  } catch {
    runnerBusy.value = false
  }
}

async function handleDeleteCohort() {
  if (!cohort.value) return
  const ok = confirm(
    `Supprimer le cohort "${cohort.value.name}" et ses ${cohort.value.iteration_count} itération(s) ?`,
  )
  if (!ok) return
  try {
    await deleteCohort(cohort.value.id)
    router.push('/lab')
  } catch (e) {
    alert(`Suppression échouée : ${(e as Error).message}`)
  }
}

function openIteration(iterationId: string) {
  router.push(`/lab/cohorts/${cohortId.value}/iterations/${iterationId}`)
}

const latestIteration = computed<IterationDetail | null>(() => {
  if (iterations.value.length === 0) return null
  return iterations.value[iterations.value.length - 1]
})

const iterationsById = computed(() => {
  const map = new Map<string, IterationDetail>()
  for (const it of iterations.value) map.set(it.id, it)
  return map
})

function getParent(it: IterationDetail): IterationDetail | null {
  if (!it.parent_iteration_id) return null
  return iterationsById.value.get(it.parent_iteration_id) ?? null
}

function zoneColor(zone: string | null): string {
  if (zone === 'green') return 'var(--success)'
  if (zone === 'orange') return 'var(--warning)'
  if (zone === 'red') return 'var(--danger)'
  return 'var(--ink-400)'
}

function formatPct(v: number | null): string {
  if (v == null) return '—'
  return `${(v * 100).toFixed(1)}%`
}
</script>

<template>
  <div class="p-8">
    <button
      class="mb-4 flex items-center gap-1 text-sm"
      style="color: var(--ink-500);"
      @click="router.push('/lab')"
    >
      <ArrowLeft class="h-3.5 w-3.5" />
      Retour au Lab
    </button>

    <div v-if="loading && !cohort" class="flex items-center gap-3 text-sm" style="color: var(--ink-500);">
      <Loader2 class="h-4 w-4 animate-spin" />
      Chargement…
    </div>
    <div
      v-else-if="error"
      class="rounded-md border px-4 py-3 text-sm"
      style="border-color: var(--danger); color: var(--ink);"
    >
      {{ error }}
    </div>

    <template v-else-if="cohort">
      <!-- Header -->
      <header class="mb-8">
        <div class="flex items-start justify-between gap-6">
          <div class="min-w-0 flex-1">
            <p
              class="mb-1 text-[10px] font-medium uppercase"
              style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
            >
              Cohort · {{ cohort.id }}
            </p>
            <div class="flex items-center gap-3">
              <h1
                class="font-display text-3xl italic font-semibold leading-tight"
                style="color: var(--indigo-700);"
              >
                {{ cohort.name }}
              </h1>
              <span
                v-if="cohort.zone"
                class="rounded-full px-2 py-0.5 text-xs font-medium"
                :style="{
                  background: `color-mix(in srgb, ${zoneColor(cohort.zone)} 14%, var(--surface))`,
                  color: zoneColor(cohort.zone),
                }"
              >{{ cohort.zone }}</span>
            </div>
            <p
              v-if="cohort.description"
              class="mt-1.5 text-sm"
              style="color: var(--ink-500);"
            >
              {{ cohort.description }}
            </p>
            <p class="mt-3 text-xs" style="color: var(--ink-500);">
              {{ cohort.eurio_ids.length }} pièces ·
              {{ cohort.iteration_count }} itération(s) ·
              meilleur R@1 : <span class="font-mono" :style="{ color: cohort.best_r_at_1 != null ? 'var(--success)' : 'var(--ink-400)' }">
                {{ formatPct(cohort.best_r_at_1) }}
              </span>
            </p>
          </div>

          <div class="flex flex-shrink-0 items-center gap-3">
            <button
              class="flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-all"
              :style="{
                background: runnerBusy ? 'var(--surface-2)' : 'var(--indigo-700)',
                color: runnerBusy ? 'var(--ink-400)' : 'white',
                cursor: runnerBusy ? 'not-allowed' : 'pointer',
                boxShadow: runnerBusy ? 'none' : 'var(--shadow-sm)',
              }"
              :disabled="runnerBusy"
              :title="runnerBusy ? 'Une itération tourne déjà' : 'Lance une nouvelle itération'"
              @click="router.push(`/lab/cohorts/${cohort.id}/iterations/new`)"
            >
              <Plus class="h-3.5 w-3.5" />
              Nouvelle itération
            </button>
            <button
              class="rounded-md border p-2 transition-colors hover:bg-[var(--surface-2)]"
              style="border-color: var(--surface-3); color: var(--ink-400);"
              title="Supprimer le cohort"
              @click="handleDeleteCohort"
            >
              <Trash2 class="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
        <div class="mt-6 h-px w-16" style="background: var(--gold);" />
      </header>

      <!-- Coin list (compact) -->
      <section class="mb-8">
        <p
          class="mb-2 text-[10px] font-medium uppercase"
          style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
        >
          Pièces (frozen)
        </p>
        <div class="flex flex-wrap gap-1.5">
          <span
            v-for="eid in cohort.eurio_ids"
            :key="eid"
            class="rounded-md border px-2 py-0.5 font-mono text-[11px]"
            style="border-color: var(--surface-3); background: var(--surface); color: var(--ink);"
          >
            {{ eid }}
          </span>
        </div>
      </section>

      <!-- Trajectory -->
      <section class="mb-8">
        <p
          class="mb-2 text-[10px] font-medium uppercase"
          style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
        >
          Trajectoire R@1
        </p>
        <TrajectoryChart :points="trajectory" @select="openIteration" />
      </section>

      <div class="grid grid-cols-1 gap-8 lg:grid-cols-[1fr_360px]">
        <!-- Iterations table -->
        <section>
          <p
            class="mb-3 text-[10px] font-medium uppercase"
            style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
          >
            Itérations
          </p>
          <div
            v-if="iterations.length === 0"
            class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed px-8 py-10 text-center"
            style="border-color: var(--surface-3);"
          >
            <p class="font-display italic text-lg" style="color: var(--ink);">
              Aucune itération encore
            </p>
            <p class="mt-1 max-w-sm text-sm" style="color: var(--ink-500);">
              Clique <span class="font-medium" style="color: var(--indigo-700);">Nouvelle itération</span>
              pour lancer la première baseline sur ce cohort.
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
                  <th class="px-4 py-2 text-left text-[10px] uppercase" style="color: var(--ink-500);">Nom / hypothèse</th>
                  <th class="px-4 py-2 text-left text-[10px] uppercase" style="color: var(--ink-500);">Δ inputs vs parent</th>
                  <th class="px-4 py-2 text-right text-[10px] uppercase" style="color: var(--ink-500);">R@1</th>
                  <th class="px-4 py-2 text-left text-[10px] uppercase" style="color: var(--ink-500);">Verdict</th>
                  <th class="px-4 py-2 text-left text-[10px] uppercase" style="color: var(--ink-500);">Date</th>
                </tr>
              </thead>
              <tbody>
                <IterationRow
                  v-for="it in iterations"
                  :key="it.id"
                  :iteration="it"
                  :parent="getParent(it)"
                  @click="openIteration(it.id)"
                />
              </tbody>
            </table>
          </div>
          <p v-if="latestIteration" class="mt-3 text-[10px]" style="color: var(--ink-400);">
            La prochaine itération pourra hériter de
            <code class="font-mono" style="color: var(--indigo-700);">{{ latestIteration.name }}</code>
            comme parent par défaut.
          </p>
        </section>

        <!-- Sensitivity sidebar -->
        <aside>
          <SensitivityPanel :entries="sensitivity" />
        </aside>
      </div>
    </template>
  </div>
</template>
