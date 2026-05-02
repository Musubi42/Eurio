<script setup lang="ts">
// Tiroir I4 — Évaluation (méta).
// 4 sous-tiroirs : I4a Studio · I4b Aug↔Real · I4c Build APK · I4d Live tests.
// Chaque sous-bloc embarque un composant existant.

import AugVsRealSection from '@/features/lab/components/AugVsRealSection.vue'
import BuildTestAppSection from '@/features/lab/components/BuildTestAppSection.vue'
import DrawerSection from '@/features/lab/components/DrawerSection.vue'
import LiveTestsSection from '@/features/lab/components/LiveTestsSection.vue'
import PerConditionTable from '@/features/lab/components/PerConditionTable.vue'
import { fetchBenchmarkRunDetail } from '@/features/lab/composables/useLabApi'
import {
  useLaunchBenchmarkMutation,
  useRunnerStatusQuery,
} from '@/features/lab/composables/useLabQueries'
import type {
  BenchmarkRunDetail,
  IterationDetail,
  IterationProgressI4,
} from '@/features/lab/types'
import { Loader2, RotateCcw } from 'lucide-vue-next'
import { computed, ref, toRefs, watch } from 'vue'

const props = defineProps<{
  cohortId: string
  iteration: IterationDetail
  progress: IterationProgressI4 | null
  locked: boolean
  lockReason: string
}>()

const { cohortId } = toRefs(props)
const iterationId = computed(() => props.iteration.id)
const launchBenchmarkMut = useLaunchBenchmarkMutation(cohortId, iterationId)
const runnerQuery = useRunnerStatusQuery()
const runnerBusy = computed(() => runnerQuery.data.value?.busy ?? false)
const launchError = ref<string | null>(null)

// "Relancer benchmark" is offered when the iteration has finished its
// training phase (status='completed') AND the studio sub-tiroir is either
// empty (never run) or partial (previous attempt failed). When the runner
// is busy on another iteration, the button is disabled with a tooltip.
const canRelaunchBenchmark = computed(() => {
  if (props.iteration.status !== 'completed') return false
  const s = props.progress?.studio.state
  return s === 'empty' || s === 'partial'
})

async function relaunchBenchmark() {
  launchError.value = null
  try {
    await launchBenchmarkMut.mutateAsync()
  }
  catch (e) {
    launchError.value = (e as Error).message
  }
}

const benchmark = ref<BenchmarkRunDetail | null>(null)

watch(
  () => props.iteration.benchmark_run_id,
  async (id) => {
    if (!id) {
      benchmark.value = null
      return
    }
    try {
      benchmark.value = await fetchBenchmarkRunDetail(id)
    }
    catch {
      benchmark.value = null
    }
  },
  { immediate: true },
)

function pct(v: number | null | undefined): string {
  if (v == null) return '—'
  return `${(v * 100).toFixed(1)}%`
}

const summary = computed(() => {
  const p = props.progress
  if (!p || p.state === 'empty') return 'Pas encore évaluée'
  const subs = [p.studio, p.aug_vs_real, p.test_app, p.live_tests]
  const ready = subs.filter(s => s.state === 'ready').length
  if (p.state === 'partial') return `${ready}/4 sous-tiroirs prêts`
  return `Studio ${pct(p.studio.r_at_1)} · Live ${pct(p.live_tests.recall_at_1)}`
})

const studioSummary = computed(() => {
  const s = props.progress?.studio
  if (!s || s.state === 'empty') return 'Aucun benchmark'
  return `R@1 = ${pct(s.r_at_1)}`
})

const avrSummary = computed(() => {
  const a = props.progress?.aug_vs_real
  if (!a || a.state === 'empty') return 'Aucune mesure DINO'
  if (a.mean_cosine == null) return 'Pas encore calculé'
  return `Cosine moyen = ${a.mean_cosine.toFixed(3)}`
})

const testAppSummary = computed(() => {
  const t = props.progress?.test_app
  if (!t || t.state === 'empty') return 'Pas prêt'
  if (t.state === 'partial') return 'TFLite manquant'
  return 'APK prêt à builder'
})

const liveSummary = computed(() => {
  const l = props.progress?.live_tests
  if (!l || l.state === 'empty') return 'Aucun test live'
  return `${l.total} tests · R@1 = ${pct(l.recall_at_1)}`
})

const deltaR1 = computed(() => props.iteration.delta_vs_parent?.r_at_1)
function formatDelta(v: number | undefined): string {
  if (v == null) return '—'
  const sign = v > 0 ? '+' : ''
  return `${sign}${(v * 100).toFixed(2)} pts`
}
function deltaColor(v: number | undefined): string {
  if (v == null) return 'var(--ink-400)'
  if (v > 0.005) return 'var(--success)'
  if (v < -0.005) return 'var(--danger)'
  return 'var(--ink-400)'
}
</script>

<template>
  <DrawerSection
    number="I4"
    title="Évaluation"
    :state="progress?.state ?? 'empty'"
    :summary="summary"
    :locked="locked"
    :lock-reason="lockReason"
  >
    <template #body>
      <div class="flex flex-col gap-3">
        <!-- I4a — Studio -->
        <DrawerSection
          number="I4a"
          title="Benchmark studio"
          :state="progress?.studio.state ?? 'empty'"
          :summary="studioSummary"
        >
          <template #body>
            <!-- Banner: empty or partial → offer to (re)run benchmark.
                 Visible only on a `completed` iteration (training+export
                 OK); on still-training iterations, the I4a state is just
                 the natural early state and no button is needed. -->
            <section
              v-if="canRelaunchBenchmark"
              class="mb-3 rounded-md border px-3 py-2 text-xs"
              :style="{
                borderColor: progress?.studio.state === 'partial' ? 'var(--danger)' : 'var(--surface-3)',
                background: progress?.studio.state === 'partial'
                  ? 'color-mix(in srgb, var(--danger) 6%, var(--surface))'
                  : 'var(--surface)',
              }"
            >
              <div class="flex items-start justify-between gap-3">
                <div class="min-w-0 flex-1">
                  <p
                    v-if="progress?.studio.state === 'partial'"
                    class="font-medium"
                    style="color: var(--danger);"
                  >
                    Benchmark précédent en échec
                  </p>
                  <p
                    v-else
                    class="font-medium"
                    style="color: var(--ink);"
                  >
                    Aucun benchmark studio
                  </p>
                  <p
                    v-if="progress?.studio.error"
                    class="mt-1 break-words font-mono"
                    style="color: var(--ink-500);"
                  >
                    {{ progress.studio.error }}
                  </p>
                  <p
                    v-else-if="progress?.studio.state === 'empty'"
                    class="mt-1"
                    style="color: var(--ink-500);"
                  >
                    Le training a réussi mais le benchmark n'a pas été lancé. Mesure le R@1 sur les captures device de la cohort.
                  </p>
                </div>
                <button
                  class="flex shrink-0 items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium"
                  :style="{
                    borderColor: 'var(--surface-3)',
                    color: (runnerBusy || launchBenchmarkMut.isPending.value) ? 'var(--ink-400)' : 'var(--ink)',
                    cursor: (runnerBusy || launchBenchmarkMut.isPending.value) ? 'not-allowed' : 'pointer',
                  }"
                  :disabled="runnerBusy || launchBenchmarkMut.isPending.value"
                  :title="runnerBusy ? 'Une itération tourne déjà' : 'Relancer evaluate_real_photos.py'"
                  @click="relaunchBenchmark"
                >
                  <Loader2 v-if="launchBenchmarkMut.isPending.value" class="h-3 w-3 animate-spin" />
                  <RotateCcw v-else class="h-3 w-3" />
                  {{ progress?.studio.state === 'partial' ? 'Relancer benchmark' : 'Lancer benchmark' }}
                </button>
              </div>
              <p
                v-if="launchError"
                class="mt-2 font-mono"
                style="color: var(--danger);"
              >
                {{ launchError }}
              </p>
            </section>

            <section class="grid grid-cols-2 gap-3 md:grid-cols-4">
              <article
                v-for="{ label, value, delta } in [
                  { label: 'R@1', value: pct(iteration.benchmark_summary?.r_at_1), delta: deltaR1 },
                  { label: 'R@3', value: pct(iteration.benchmark_summary?.r_at_3), delta: iteration.delta_vs_parent?.r_at_3 },
                  { label: 'R@5', value: pct(iteration.benchmark_summary?.r_at_5), delta: iteration.delta_vs_parent?.r_at_5 },
                  { label: 'Spread', value: iteration.benchmark_summary?.mean_spread != null ? iteration.benchmark_summary.mean_spread.toFixed(3) : '—', delta: undefined },
                ]"
                :key="label"
                class="rounded-lg border p-3"
                style="border-color: var(--surface-3); background: var(--surface);"
              >
                <p class="text-[10px] font-medium uppercase" style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
                  {{ label }}
                </p>
                <p class="mt-1 font-display text-2xl font-semibold tabular-nums leading-none" style="color: var(--indigo-700);">
                  {{ value }}
                </p>
                <p
                  v-if="delta !== undefined"
                  class="mt-1 font-mono text-xs tabular-nums"
                  :style="{ color: deltaColor(delta) }"
                >
                  {{ formatDelta(delta) }} vs parent
                </p>
              </article>
            </section>

            <section
              v-if="benchmark && Object.keys(benchmark.per_condition ?? {}).length > 0"
              class="mt-4"
            >
              <p
                class="mb-2 text-[10px] font-medium uppercase"
                style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
              >
                Par axe de variabilité (photos réelles)
              </p>
              <PerConditionTable :per-condition="benchmark.per_condition ?? {}" />
            </section>
          </template>
        </DrawerSection>

        <!-- I4b — Aug ↔ réelles -->
        <DrawerSection
          number="I4b"
          title="Aug ↔ réelles (DINO)"
          :state="progress?.aug_vs_real.state ?? 'empty'"
          :summary="avrSummary"
        >
          <template #body>
            <AugVsRealSection :cohort-id="cohortId" :iteration-id="iteration.id" />
          </template>
        </DrawerSection>

        <!-- I4c — Build APK -->
        <DrawerSection
          number="I4c"
          title="Build cohortTest APK"
          :state="progress?.test_app.state ?? 'empty'"
          :summary="testAppSummary"
        >
          <template #body>
            <BuildTestAppSection
              :cohort-id="cohortId"
              :iteration-id="iteration.id"
              :status="iteration.status"
            />
          </template>
        </DrawerSection>

        <!-- I4d — Live tests -->
        <DrawerSection
          number="I4d"
          title="Live tests device"
          :state="progress?.live_tests.state ?? 'empty'"
          :summary="liveSummary"
        >
          <template #body>
            <LiveTestsSection :cohort-id="cohortId" :iteration-id="iteration.id" />
          </template>
        </DrawerSection>
      </div>
    </template>
  </DrawerSection>
</template>
