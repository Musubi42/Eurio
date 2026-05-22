<script setup lang="ts">
import { computed } from 'vue'
import { Star } from 'lucide-vue-next'
import type { BenchMetrics } from '../composables/useBenchApi'

const props = defineProps<{ metrics: BenchMetrics }>()

function pct(rate: number | null): string {
  return rate == null ? '—' : `${(rate * 100).toFixed(1)} %`
}

interface Stat {
  label: string
  value: string
  detail: string
  star?: boolean
  tone?: string
}

const stats = computed<Stat[]>(() => {
  const m = props.metrics
  return [
    {
      label: 'Faux rejet',
      value: pct(m.false_discard_rate),
      detail: `${m.n_false_discard} / ${m.n_valid} valides`,
      tone: m.n_false_discard > 0 ? 'var(--danger)' : 'var(--success)',
    },
    {
      label: 'Recall',
      value: pct(m.recall_rate),
      detail: `${m.n_valid - m.n_false_discard} / ${m.n_valid} gardées`,
    },
    {
      label: 'Auto-attribution',
      value: pct(m.auto_attribution_rate),
      detail: `${m.n_auto_correct} / ${m.n_valid} auto`,
      star: true,
    },
    {
      label: 'Review',
      value: pct(m.review_rate),
      detail: `${m.n_kept_review} / ${m.n_valid} en file`,
    },
    {
      label: 'Précision',
      value: pct(m.precision),
      detail: `${m.n_auto_wrong} auto erronée${m.n_auto_wrong > 1 ? 's' : ''}`,
      tone: m.n_auto_wrong > 0 ? 'var(--danger)' : undefined,
    },
    {
      label: 'Junk false-keep',
      value: pct(m.false_keep_rate),
      detail: `${m.n_false_keep} / ${m.n_junk} junk gardé`,
      tone: 'var(--gold-600)',
    },
  ]
})
</script>

<template>
  <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
    <div
      v-for="s in stats"
      :key="s.label"
      class="rounded-lg border px-3.5 py-3"
      :style="s.star
        ? 'border-color: var(--indigo-600); background: var(--indigo-50);'
        : 'border-color: var(--surface-3); background: var(--surface-1);'"
    >
      <div class="flex items-center gap-1 text-[11px] font-medium uppercase tracking-wider"
           style="color: var(--ink-400);">
        <Star v-if="s.star" class="h-3 w-3" :fill="'var(--indigo-600)'"
              style="color: var(--indigo-600);" />
        {{ s.label }}
      </div>
      <div class="mt-1 font-display text-2xl font-semibold"
           :style="`color: ${s.tone ?? (s.star ? 'var(--indigo-700)' : 'var(--ink-700)')};`">
        {{ s.value }}
      </div>
      <div class="text-[11px]" style="color: var(--ink-400);">{{ s.detail }}</div>
    </div>
  </div>
</template>
