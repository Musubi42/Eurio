<script setup lang="ts">
// Phase 5 — Live training monitor.
// Reads /lab/runner/training-progress/<iid> every 2s while iteration is
// running. Displays phase + epoch/loss/ETA + tail des stdout lines.

import { useTrainingProgressQuery } from '@/features/lab/composables/useLabQueries'
import {
  useStopIterationMutation,
} from '@/features/lab/composables/useLabQueries'
import type {
  IterationDetail,
  TrainingProgress,
  TrainingProgressPhase,
} from '@/features/lab/types'
import { Loader2, Square } from 'lucide-vue-next'
import { computed, toRefs } from 'vue'

const props = defineProps<{
  cohortId: string
  iteration: IterationDetail
}>()

const { cohortId } = toRefs(props)
const iterationId = computed(() => props.iteration.id)
const status = computed(() => props.iteration.status)

const query = useTrainingProgressQuery(iterationId, status)
const progress = computed<TrainingProgress | null>(() => query.data.value ?? null)

const stopMut = useStopIterationMutation(cohortId)

const phase = computed<TrainingProgressPhase>(() => progress.value?.phase ?? 'unknown')

const phaseLabel: Record<TrainingProgressPhase, string> = {
  unknown: 'En attente…',
  bake: 'Bake en cours…',
  training: 'Training en cours',
  training_done: 'Training terminé · export TFLite…',
  export: 'Export TFLite…',
  benchmark: 'Benchmark en cours…',
  done: 'Terminé',
  failed: 'Échec',
}

const pct = computed(() => {
  const p = progress.value
  if (!p?.epoch_current || !p?.epochs_total) return 0
  return Math.min(100, Math.round((p.epoch_current / p.epochs_total) * 100))
})

function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || seconds < 0) return '—'
  const s = Math.floor(seconds)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const r = s - m * 60
  if (m < 60) return r > 0 ? `${m}m ${r}s` : `${m}m`
  const h = Math.floor(m / 60)
  const mr = m - h * 60
  return mr > 0 ? `${h}h ${mr}m` : `${h}h`
}

async function handleStop() {
  if (!confirm('Stopper l\'itération en cours ? Le training sera interrompu.')) return
  try {
    await stopMut.mutateAsync(props.iteration.id)
  }
  catch (e) {
    alert(`Stop échoué : ${(e as Error).message}`)
  }
}

const tail = computed<string[]>(() => progress.value?.log_tail ?? [])
</script>

<template>
  <div
    class="rounded-lg border p-4"
    style="border-color: var(--indigo-700); background: color-mix(in srgb, var(--indigo-700) 4%, var(--surface));"
  >
    <!-- Header : phase + Stop -->
    <div class="mb-4 flex items-center justify-between gap-3">
      <div class="flex items-center gap-2">
        <Loader2
          v-if="phase === 'bake' || phase === 'training' || phase === 'training_done' || phase === 'export' || phase === 'benchmark'"
          class="h-4 w-4 animate-spin"
          style="color: var(--indigo-700);"
        />
        <p class="font-medium text-sm" style="color: var(--ink);">
          Phase : <span style="color: var(--indigo-700);">{{ phaseLabel[phase] }}</span>
        </p>
      </div>
      <button
        v-if="phase === 'training' || phase === 'benchmark' || phase === 'bake' || phase === 'export'"
        class="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium"
        :style="{
          borderColor: 'var(--danger)',
          color: stopMut.isPending.value ? 'var(--ink-400)' : 'var(--danger)',
          cursor: stopMut.isPending.value ? 'wait' : 'pointer',
        }"
        :disabled="stopMut.isPending.value"
        @click="handleStop"
      >
        <Loader2 v-if="stopMut.isPending.value" class="h-3 w-3 animate-spin" />
        <Square v-else class="h-3 w-3" />
        Stopper
      </button>
    </div>

    <!-- Runtime confirmé + augmentations -->
    <dl class="mb-4 grid grid-cols-2 gap-3 text-xs">
      <div>
        <dt style="color: var(--ink-500);">Device confirmé</dt>
        <dd class="font-mono" style="color: var(--ink);">
          {{ progress?.device || '—' }}
        </dd>
      </div>
      <div>
        <dt style="color: var(--ink-500);">Augmentations runtime</dt>
        <dd
          class="font-mono"
          :style="{
            color: progress?.augmentations_runtime === 'disabled'
              ? 'var(--success)'
              : 'var(--warning)',
          }"
        >
          {{ progress?.augmentations_runtime || '—' }}
          <span
            v-if="progress?.augmentations_runtime === 'disabled'"
            style="color: var(--ink-400);"
          > (bake-only)</span>
        </dd>
      </div>
    </dl>

    <!-- Epoch progress -->
    <div v-if="phase === 'training' && progress?.epochs_total" class="mb-4">
      <div class="mb-1 flex items-center justify-between text-xs">
        <span style="color: var(--ink);">
          Epoch <span class="font-mono">{{ progress.epoch_current ?? 0 }}</span>
          / <span class="font-mono">{{ progress.epochs_total }}</span>
        </span>
        <span class="font-mono" style="color: var(--indigo-700);">{{ pct }}%</span>
      </div>
      <div
        class="h-2 overflow-hidden rounded-full"
        style="background: var(--surface-2);"
      >
        <div
          class="h-full transition-all duration-500"
          :style="{ width: `${pct}%`, background: 'var(--indigo-700)' }"
        />
      </div>
      <div class="mt-2 grid grid-cols-2 gap-3 text-xs">
        <div>
          <span style="color: var(--ink-500);">Loss : </span>
          <span class="font-mono" style="color: var(--ink);">
            {{ progress.loss_current?.toFixed(4) ?? '—' }}
          </span>
          <span style="color: var(--ink-500);"> · best : </span>
          <span class="font-mono" style="color: var(--success);">
            {{ progress.loss_best?.toFixed(4) ?? '—' }}
          </span>
        </div>
        <div class="text-right">
          <span style="color: var(--ink-500);">Temps : </span>
          <span class="font-mono" style="color: var(--ink);">
            {{ formatDuration(progress.elapsed_seconds) }}
          </span>
          <span style="color: var(--ink-500);"> · ETA : </span>
          <span class="font-mono" style="color: var(--ink);">
            ~{{ formatDuration(progress.eta_seconds) }}
          </span>
        </div>
      </div>
    </div>

    <!-- Log tail -->
    <details class="mt-2">
      <summary class="cursor-pointer text-xs" style="color: var(--ink-500);">
        ▾ Logs ({{ tail.length }} dernière{{ tail.length > 1 ? 's' : '' }} ligne{{ tail.length > 1 ? 's' : '' }})
      </summary>
      <pre
        class="mt-2 max-h-64 overflow-auto rounded-md border p-2 font-mono text-[11px]"
        style="border-color: var(--surface-3); background: var(--surface-1); color: var(--ink-500);"
      ><span v-for="(line, i) in tail" :key="i">{{ line }}
</span><span v-if="tail.length === 0" style="color: var(--ink-400);">(aucune ligne capturée)</span></pre>
    </details>

    <!-- Failure detail -->
    <p
      v-if="phase === 'failed' && progress?.error"
      class="mt-3 rounded-md border px-3 py-2 text-xs"
      style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 6%, var(--surface)); color: var(--ink);"
    >
      {{ progress.error }}
    </p>
  </div>
</template>
