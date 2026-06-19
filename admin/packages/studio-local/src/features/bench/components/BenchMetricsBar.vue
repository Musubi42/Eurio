<script setup lang="ts">
import { computed } from 'vue'
import { Star } from 'lucide-vue-next'
import type { BenchMetrics } from '../composables/useBenchApi'

const props = defineProps<{ metrics: BenchMetrics }>()

function pct(rate: number | null): string {
  return rate == null ? '—' : `${(rate * 100).toFixed(1)}`
}

interface Stat {
  label: string
  value: string
  unit: string
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
      unit: '%',
      detail: `${m.n_false_discard} / ${m.n_valid} valides`,
      tone: m.n_false_discard > 0 ? 'var(--danger)' : 'var(--success)',
    },
    {
      label: 'Recall',
      value: pct(m.recall_rate),
      unit: '%',
      detail: `${m.n_valid - m.n_false_discard} gardées`,
    },
    {
      label: 'Auto-attribution',
      value: pct(m.auto_attribution_rate),
      unit: '%',
      detail: `${m.n_auto_correct} / ${m.n_valid} auto`,
      star: true,
    },
    {
      label: 'Review',
      value: pct(m.review_rate),
      unit: '%',
      detail: `${m.n_kept_review} en file`,
    },
    {
      label: 'Précision',
      value: pct(m.precision),
      unit: '%',
      detail: `${m.n_auto_wrong} erronée${m.n_auto_wrong > 1 ? 's' : ''}`,
      tone: m.n_auto_wrong > 0 ? 'var(--danger)' : undefined,
    },
    {
      label: 'Junk false-keep',
      value: pct(m.false_keep_rate),
      unit: '%',
      detail: `${m.n_false_keep} / ${m.n_junk} gardé`,
      tone: 'var(--gold-700)',
    },
  ]
})
</script>

<template>
  <div
    class="flex overflow-hidden rounded-xl border"
    style="border-color: var(--surface-3); background: var(--surface);"
  >
    <div
      v-for="(s, i) in stats"
      :key="s.label"
      class="relative flex-1 px-5 py-3.5"
      :style="i > 0 ? 'border-left: 1px solid var(--surface-3);' : ''"
    >
      <!-- Liseré indigo sous la métrique étoile -->
      <div
        v-if="s.star"
        class="absolute inset-x-0 bottom-0 h-[3px]"
        style="background: var(--indigo-600);"
      />
      <div
        class="flex items-center gap-1 text-[10.5px] font-medium uppercase tracking-[0.08em]"
        style="color: var(--ink-400);"
      >
        <Star
          v-if="s.star"
          class="h-3 w-3"
          fill="var(--indigo-600)"
          style="color: var(--indigo-600);"
        />
        {{ s.label }}
      </div>
      <div class="mt-1.5 flex items-baseline gap-0.5">
        <span
          class="text-[28px] leading-none"
          style="font-family: var(--font-display); font-weight: 600;"
          :style="`font-family: var(--font-display); font-weight: 600; color: ${
            s.tone ?? (s.star ? 'var(--indigo-700)' : 'var(--ink)')};`"
        >{{ s.value }}</span>
        <span class="text-sm" style="color: var(--ink-400);">{{ s.unit }}</span>
      </div>
      <div class="mt-0.5 text-[11px]" style="color: var(--ink-400);">
        {{ s.detail }}
      </div>
    </div>
  </div>
</template>
