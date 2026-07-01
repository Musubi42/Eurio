<script setup lang="ts">
import type { IterationDetail } from '../types'
import InputDiffChip from './InputDiffChip.vue'
import VerdictBadge from './VerdictBadge.vue'
import { useStopIterationMutation } from '@/features/lab/composables/useLabQueries'
import { Loader2, Square } from 'lucide-vue-next'
import { computed } from 'vue'

const props = defineProps<{
  iteration: IterationDetail
  parent?: IterationDetail | null
  /** Machine courante (mac/pc) — pour l'origine + le gating (R3). */
  currentMachine?: string | null
}>()

const emit = defineEmits<{
  (e: 'click'): void
}>()

// R3 : origine de l'itération. « Cross-origin » = calculée sur une AUTRE machine
// → ses artefacts (tflite/checkpoints/logs) ne sont pas ici, la page détail
// (ML local) 404erait → on la rend consultable mais non-ouvrable.
const origin = computed(() => props.iteration.created_on ?? null)
const crossOrigin = computed(() =>
  !!(origin.value && props.currentMachine && origin.value !== props.currentMachine),
)

function onRowClick() {
  if (crossOrigin.value) return
  emit('click')
}

const stopMutation = useStopIterationMutation(() => props.iteration.cohort_id)

async function handleStop(event: Event) {
  // Prevent the row click from racing the navigation.
  event.stopPropagation()
  if (!confirm(`Stopper l'itération « ${props.iteration.name} » ?\nLe training termine l'epoch en cours puis sort proprement (timeout 30s sinon SIGKILL).`)) {
    return
  }
  try {
    await stopMutation.mutateAsync(props.iteration.id)
  } catch (e) {
    alert(`Stop échoué : ${(e as Error).message}`)
  }
}

function formatPct(v: number | null | undefined): string {
  if (v == null) return '—'
  return `${(v * 100).toFixed(1)}%`
}

function deltaText(v: number | undefined): string {
  if (v == null) return ''
  const sign = v > 0 ? '+' : ''
  return `${sign}${(v * 100).toFixed(1)}pt`
}

function deltaColor(v: number | undefined): string {
  if (v == null) return 'var(--ink-400)'
  if (v > 0.005) return 'var(--success)'
  if (v < -0.005) return 'var(--danger)'
  return 'var(--ink-400)'
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('fr-FR', {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
  })
}

const inProgress = computed(() =>
  props.iteration.status === 'training' || props.iteration.status === 'benchmarking',
)

const r1 = computed(() => props.iteration.benchmark_summary?.r_at_1 ?? null)
const deltaR1 = computed(() => props.iteration.delta_vs_parent?.r_at_1)
</script>

<template>
  <tr
    class="border-b transition-colors"
    :class="crossOrigin
      ? 'cursor-default'
      : 'cursor-pointer hover:bg-[color-mix(in_srgb,var(--indigo-700)_3%,var(--surface))]'"
    :style="{ borderColor: 'var(--surface-3)', opacity: crossOrigin ? 0.6 : 1 }"
    :title="crossOrigin ? `Itération calculée sur « ${origin} » — artefacts sur cette machine, ouvre-la depuis là-bas` : undefined"
    @click="onRowClick"
  >
    <td class="px-4 py-2">
      <div class="font-medium" style="color: var(--ink);">{{ iteration.name }}</div>
      <div
        v-if="iteration.hypothesis"
        class="mt-0.5 line-clamp-1 text-xs italic"
        style="color: var(--ink-500);"
      >
        « {{ iteration.hypothesis }} »
      </div>
    </td>
    <td class="px-4 py-2 align-top">
      <InputDiffChip :diff="iteration.diff_from_parent" />
    </td>
    <td class="px-4 py-2 text-right align-top">
      <template v-if="inProgress">
        <div class="flex items-center justify-end gap-2">
          <span class="inline-flex items-center gap-1 text-xs" style="color: var(--warning);">
            <Loader2 class="h-3 w-3 animate-spin" />
            {{ iteration.status === 'training' ? 'training' : 'bench' }}
          </span>
          <button
            class="inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] uppercase transition-colors hover:bg-[var(--surface-2)]"
            style="border-color: var(--danger); color: var(--danger); letter-spacing: var(--tracking-eyebrow);"
            :disabled="stopMutation.isPending.value"
            title="Stopper proprement (SIGTERM, 30s puis SIGKILL)"
            @click="handleStop"
          >
            <Loader2 v-if="stopMutation.isPending.value" class="h-2.5 w-2.5 animate-spin" />
            <Square v-else class="h-2.5 w-2.5" />
            Stop
          </button>
        </div>
      </template>
      <template v-else>
        <span class="font-mono tabular-nums" style="color: var(--indigo-700);">
          {{ formatPct(r1) }}
        </span>
        <span
          v-if="deltaR1 != null"
          class="ml-1 font-mono text-[10px] tabular-nums"
          :style="{ color: deltaColor(deltaR1) }"
        >
          {{ deltaText(deltaR1) }}
        </span>
      </template>
    </td>
    <td class="px-4 py-2 align-top">
      <VerdictBadge
        :verdict="iteration.verdict"
        :override="iteration.verdict_override"
      />
    </td>
    <td class="px-4 py-2 text-xs align-top" style="color: var(--ink-500);">
      {{ formatDate(iteration.created_at) }}
    </td>
    <td class="px-4 py-2 align-top">
      <span
        v-if="origin"
        class="inline-flex items-center rounded-md px-1.5 py-0.5 font-mono text-[10px] uppercase"
        :style="{
          letterSpacing: 'var(--tracking-eyebrow)',
          background: crossOrigin ? 'var(--surface-2)' : 'color-mix(in srgb, var(--indigo-700) 12%, var(--surface))',
          color: crossOrigin ? 'var(--ink-500)' : 'var(--indigo-700)',
        }"
      >{{ origin }}</span>
      <span v-else class="text-xs" style="color: var(--ink-400);">—</span>
    </td>
  </tr>
</template>
