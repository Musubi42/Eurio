<script setup lang="ts">
import { computed } from 'vue'

defineProps<{
  // Shape: { lighting: { "natural-direct": { r_at_1, r_at_3, num_photos }, ... }, angle: {...}, ... }
  perCondition: Record<string, Record<string, { r_at_1: number; r_at_3: number; num_photos: number }>>
}>()

const AXIS_LABELS: Record<string, string> = {
  lighting: 'Éclairage',
  background: 'Fond',
  angle: 'Angle',
  distance: 'Distance',
  state: 'État',
}

function formatPct(v: number): string {
  return `${(v * 100).toFixed(1)}%`
}

function tint(r_at_1: number): string {
  if (r_at_1 >= 0.85) return 'var(--success)'
  if (r_at_1 >= 0.70) return 'var(--warning)'
  return 'var(--danger)'
}
</script>

<template>
  <div class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
    <article
      v-for="(values, axis) in perCondition"
      :key="axis"
      class="rounded-lg border p-4"
      style="border-color: var(--surface-3); background: var(--surface);"
    >
      <p
        class="mb-2 text-[10px] font-medium uppercase"
        style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);"
      >
        {{ AXIS_LABELS[axis] ?? axis }}
      </p>
      <table class="w-full text-xs">
        <tbody>
          <tr
            v-for="(metrics, value) in values"
            :key="value"
            class="border-b last:border-b-0"
            style="border-color: var(--surface-3);"
          >
            <td class="py-1 font-mono" style="color: var(--ink);">{{ value }}</td>
            <td
              class="py-1 text-right font-mono tabular-nums"
              :style="{ color: tint(metrics.r_at_1) }"
            >
              {{ formatPct(metrics.r_at_1) }}
            </td>
            <td class="py-1 pl-2 text-right font-mono tabular-nums" style="color: var(--ink-400);">
              n={{ metrics.num_photos }}
            </td>
          </tr>
        </tbody>
      </table>
    </article>
  </div>
</template>
