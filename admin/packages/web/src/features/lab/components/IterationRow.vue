<script setup lang="ts">
import type { IterationDetail } from '../types'
import InputDiffChip from './InputDiffChip.vue'
import VerdictBadge from './VerdictBadge.vue'
import { Loader2 } from 'lucide-vue-next'
import { computed } from 'vue'

const props = defineProps<{
  iteration: IterationDetail
  parent?: IterationDetail | null
}>()

defineEmits<{
  (e: 'click'): void
}>()

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
    class="cursor-pointer border-b transition-colors hover:bg-[color-mix(in_srgb,var(--indigo-700)_3%,var(--surface))]"
    style="border-color: var(--surface-3);"
    @click="$emit('click')"
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
        <span class="inline-flex items-center gap-1 text-xs" style="color: var(--warning);">
          <Loader2 class="h-3 w-3 animate-spin" />
          {{ iteration.status === 'training' ? 'training' : 'bench' }}
        </span>
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
  </tr>
</template>
