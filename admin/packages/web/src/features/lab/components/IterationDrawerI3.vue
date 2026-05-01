<script setup lang="ts">
// Tiroir I3 — Training (coquille).
// Phase 4 ajoute la carte runtime ; phase 5 ajoute le monitor live.

import DrawerSection from '@/features/lab/components/DrawerSection.vue'
import RuntimeBadge from '@/features/lab/components/RuntimeBadge.vue'
import TrainingMonitor from '@/features/lab/components/TrainingMonitor.vue'
import {
  useLaunchTrainingMutation,
  useRunnerStatusQuery,
} from '@/features/lab/composables/useLabQueries'
import type {
  IterationDetail,
  IterationProgressI3,
} from '@/features/lab/types'
import { Loader2, Play, RotateCcw } from 'lucide-vue-next'
import { computed, ref, toRefs } from 'vue'

const props = defineProps<{
  cohortId: string
  iteration: IterationDetail
  progress: IterationProgressI3 | null
  locked: boolean
  lockReason: string
}>()

const { cohortId } = toRefs(props)
const iterationId = computed(() => props.iteration.id)

const launchMut = useLaunchTrainingMutation(cohortId, iterationId)
const runnerQuery = useRunnerStatusQuery()
const runnerBusy = computed(() => runnerQuery.data.value?.busy ?? false)
const error = ref<string | null>(null)

const status = computed(() => props.iteration.status)
const isRunning = computed(() => status.value === 'training' || status.value === 'benchmarking')

const summary = computed(() => {
  const p = props.progress
  if (!p) return 'Chargement…'
  if (p.state === 'empty') return 'Pas encore lancé'
  if (p.state === 'running') return `Training en cours · ${p.status}`
  if (p.state === 'partial') return `Échec · ${p.failure_reason ?? 'voir détail'}`
  const r = props.iteration.benchmark_summary?.r_at_1
  if (r != null) return `Training terminé · R@1 = ${(r * 100).toFixed(1)}%`
  return 'Training terminé'
})

async function launch() {
  error.value = null
  try {
    await launchMut.mutateAsync()
  }
  catch (e) {
    error.value = (e as Error).message
  }
}
</script>

<template>
  <DrawerSection
    number="I3"
    title="Training"
    :state="progress?.state ?? 'empty'"
    :summary="summary"
    :locked="locked"
    :lock-reason="lockReason"
  >
    <template #body>
      <!-- pending : carte runtime + bouton Lancer -->
      <div v-if="status === 'pending'">
        <RuntimeBadge class="mb-4" />
        <p class="mb-3 text-xs" style="color: var(--ink-500);">
          Le training tournera sur ce matos. Vérifie que c'est ce que tu attends.
        </p>
        <div class="flex items-center justify-end">
          <button
            class="flex items-center gap-1.5 rounded-md px-4 py-2 text-sm font-medium"
            :style="{
              background: (runnerBusy || launchMut.isPending.value) ? 'var(--surface-2)' : 'var(--indigo-700)',
              color: (runnerBusy || launchMut.isPending.value) ? 'var(--ink-400)' : 'white',
              cursor: (runnerBusy || launchMut.isPending.value) ? 'not-allowed' : 'pointer',
            }"
            :disabled="runnerBusy || launchMut.isPending.value"
            :title="runnerBusy ? 'Une itération tourne déjà' : 'Lancer training + benchmark'"
            @click="launch"
          >
            <Loader2 v-if="launchMut.isPending.value" class="h-3.5 w-3.5 animate-spin" />
            <Play v-else class="h-3.5 w-3.5" />
            Lancer training
          </button>
        </div>
      </div>

      <!-- running : monitor live (phase 5) -->
      <div v-else-if="isRunning">
        <TrainingMonitor :cohort-id="cohortId" :iteration="iteration" />
      </div>

      <!-- completed : recap -->
      <div v-else-if="status === 'completed'" class="text-sm" style="color: var(--ink);">
        <dl class="grid grid-cols-2 gap-3">
          <div>
            <dt class="text-[10px] uppercase" style="color: var(--ink-500);">Démarré</dt>
            <dd class="mt-0.5 font-mono text-xs">{{ progress?.started_at || '—' }}</dd>
          </div>
          <div>
            <dt class="text-[10px] uppercase" style="color: var(--ink-500);">Fini</dt>
            <dd class="mt-0.5 font-mono text-xs">{{ progress?.finished_at || '—' }}</dd>
          </div>
          <div>
            <dt class="text-[10px] uppercase" style="color: var(--ink-500);">Training run</dt>
            <dd class="mt-0.5 font-mono text-xs">
              {{ iteration.training_summary?.version ? `v${iteration.training_summary.version}` : (progress?.training_run_id ?? '—') }}
            </dd>
          </div>
          <div>
            <dt class="text-[10px] uppercase" style="color: var(--ink-500);">Recall@1 (training)</dt>
            <dd class="mt-0.5 font-mono text-xs">
              {{ iteration.training_summary?.recall_at_1 != null
                ? `${(iteration.training_summary.recall_at_1 * 100).toFixed(1)}%`
                : '—' }}
            </dd>
          </div>
        </dl>
      </div>

      <!-- failed : message + retry -->
      <div v-else-if="status === 'failed'">
        <div
          class="mb-3 rounded-md border px-3 py-2 text-xs"
          style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 6%, var(--surface)); color: var(--ink);"
        >
          <p class="font-medium" style="color: var(--danger);">Itération en échec</p>
          <p class="mt-1 font-mono">{{ progress?.failure_reason || iteration.error || 'aucun détail' }}</p>
        </div>
        <div class="flex items-center justify-end">
          <button
            class="flex items-center gap-1.5 rounded-md border px-3 py-2 text-xs font-medium"
            :style="{
              borderColor: 'var(--surface-3)',
              color: launchMut.isPending.value ? 'var(--ink-400)' : 'var(--ink)',
              cursor: launchMut.isPending.value ? 'wait' : 'pointer',
            }"
            :disabled="launchMut.isPending.value || runnerBusy"
            @click="launch"
          >
            <Loader2 v-if="launchMut.isPending.value" class="h-3 w-3 animate-spin" />
            <RotateCcw v-else class="h-3 w-3" />
            Retry
          </button>
        </div>
      </div>

      <p v-if="error" class="mt-3 rounded-md border px-3 py-2 text-xs" style="border-color: var(--danger); color: var(--ink);">
        {{ error }}
      </p>
    </template>
  </DrawerSection>
</template>
