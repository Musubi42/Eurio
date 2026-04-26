<script setup lang="ts">
import type { TrajectoryPoint } from '../types'
import { computed } from 'vue'

const props = defineProps<{
  points: TrajectoryPoint[]
}>()

const usable = computed(() => props.points.filter(p => p.r_at_1 != null))

const H = 140
const W = 640
const PAD = 32

const layout = computed(() => {
  if (usable.value.length === 0) return null
  const vals = usable.value.map(p => p.r_at_1 as number)
  const min = Math.max(0, Math.min(...vals) - 0.05)
  const max = Math.min(1, Math.max(...vals) + 0.05)
  const span = Math.max(max - min, 0.01)
  const step = usable.value.length > 1 ? (W - 2 * PAD) / (usable.value.length - 1) : 0
  return usable.value.map((p, i) => ({
    x: PAD + i * step,
    y: H - PAD - ((p.r_at_1! - min) / span) * (H - 2 * PAD),
    value: p.r_at_1,
    name: p.name,
    verdict: p.verdict,
    id: p.iteration_id,
  }))
})

function dotColor(verdict: string | null): string {
  if (verdict === 'better') return 'var(--success)'
  if (verdict === 'worse') return 'var(--danger)'
  if (verdict === 'mixed') return 'var(--warning)'
  if (verdict === 'baseline') return 'var(--indigo-700)'
  return 'var(--ink-400)'
}

const pathD = computed(() => {
  if (!layout.value || layout.value.length < 2) return ''
  return layout.value.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ')
})

const emit = defineEmits<{
  (e: 'select', iterationId: string): void
}>()
</script>

<template>
  <div
    v-if="!layout || usable.length === 0"
    class="flex items-center justify-center rounded-lg border-2 border-dashed px-8 py-10 text-sm italic"
    style="border-color: var(--surface-3); color: var(--ink-400);"
  >
    Aucune itération complétée pour l'instant.
  </div>
  <div
    v-else
    class="rounded-lg border p-4"
    style="border-color: var(--surface-3); background: var(--surface);"
  >
    <svg :viewBox="`0 0 ${W} ${H}`" class="w-full" style="max-height: 180px;">
      <!-- baseline grid -->
      <line
        :x1="PAD" :y1="H - PAD" :x2="W - PAD" :y2="H - PAD"
        stroke="var(--surface-3)" stroke-width="1"
      />
      <!-- trajectory -->
      <path
        :d="pathD"
        fill="none"
        stroke="var(--indigo-700)"
        stroke-width="1.5"
        opacity="0.6"
      />
      <g v-for="(p, i) in layout" :key="p.id">
        <circle
          :cx="p.x" :cy="p.y" r="5"
          :fill="dotColor(p.verdict)"
          stroke="var(--surface)"
          stroke-width="2"
          style="cursor: pointer;"
          @click="emit('select', p.id)"
        >
          <title>{{ p.name }} — R@1 {{ (p.value! * 100).toFixed(1) }}%</title>
        </circle>
        <text
          v-if="i === 0 || i === layout!.length - 1"
          :x="p.x"
          :y="p.y - 10"
          text-anchor="middle"
          class="font-mono"
          style="fill: var(--ink-500); font-size: 10px;"
        >
          {{ ((p.value ?? 0) * 100).toFixed(1) }}%
        </text>
      </g>
    </svg>
  </div>
</template>
