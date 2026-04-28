<script setup lang="ts">
import { computed } from 'vue'
import { Minus, TrendingDown, TrendingUp } from 'lucide-vue-next'
import type { SourceDelta } from '../composables/useSourcesApi'

const props = defineProps<{
  delta: SourceDelta | null
  /** When true, render the price-evolution variant (eBay). Else: counts only. */
  hasPriceDelta?: boolean
}>()

const direction = computed<'up' | 'down' | 'flat' | 'idle'>(() => {
  if (!props.delta) return 'idle'
  if (props.hasPriceDelta && props.delta.delta_p50_median_pct !== null) {
    if (props.delta.delta_p50_median_pct > 0.1) return 'up'
    if (props.delta.delta_p50_median_pct < -0.1) return 'down'
    return 'flat'
  }
  if (props.delta.n_new > 0) return 'up'
  if (props.delta.n_dropped > 0 && props.delta.n_new === 0) return 'down'
  return 'flat'
})

const tone = computed(() => {
  switch (direction.value) {
    case 'up':
      return 'var(--success)'
    case 'down':
      return 'var(--danger)'
    default:
      return 'var(--ink-500)'
  }
})
</script>

<template>
  <div v-if="!delta" class="text-xs italic" style="color: var(--ink-500);">
    — pas de delta calculable
  </div>

  <div v-else class="space-y-0.5">
    <!-- Primary line -->
    <div class="flex items-center gap-1.5">
      <component
        :is="direction === 'up' ? TrendingUp : direction === 'down' ? TrendingDown : Minus"
        class="h-3.5 w-3.5"
        :style="{ color: tone }"
      />
      <p
        v-if="hasPriceDelta && delta.delta_p50_median_pct !== null"
        class="font-mono text-xs font-medium tabular-nums"
        :style="{ color: tone }"
      >
        {{ delta.delta_p50_median_pct > 0 ? '+' : '' }}{{ delta.delta_p50_median_pct.toFixed(1) }}%
        <span class="font-normal opacity-70">P50 (médiane)</span>
      </p>
      <p
        v-else-if="delta.n_new > 0"
        class="font-mono text-xs font-medium"
        :style="{ color: tone }"
      >
        +{{ delta.n_new }}
        <span class="font-normal opacity-70">
          {{ delta.n_new === 1 ? 'nouvelle pièce' : 'nouvelles pièces' }}
        </span>
      </p>
      <p
        v-else-if="delta.n_dropped > 0"
        class="font-mono text-xs font-medium"
        :style="{ color: tone }"
      >
        −{{ delta.n_dropped }}
        <span class="font-normal opacity-70">
          {{ delta.n_dropped === 1 ? 'perdue' : 'perdues' }}
        </span>
      </p>
      <p
        v-else
        class="font-mono text-xs"
        style="color: var(--ink-500);"
      >
        aucun changement
      </p>
    </div>

    <!-- Secondary line: stable + new for eBay, or new + dropped breakdown otherwise -->
    <p
      v-if="hasPriceDelta"
      class="text-[11px] leading-snug"
      style="color: var(--ink-500);"
    >
      <span v-if="delta.n_stable !== null">{{ delta.n_stable }} stables</span>
      <span v-if="delta.n_new > 0"> · +{{ delta.n_new }} nouvelle{{ delta.n_new > 1 ? 's' : '' }}</span>
      <span v-if="delta.n_dropped > 0"> · −{{ delta.n_dropped }} perdue{{ delta.n_dropped > 1 ? 's' : '' }}</span>
    </p>
    <p
      v-else-if="delta.n_dropped > 0 && delta.n_new > 0"
      class="text-[11px]"
      style="color: var(--ink-500);"
    >
      −{{ delta.n_dropped }} perdue{{ delta.n_dropped > 1 ? 's' : '' }}
    </p>

    <!-- Swing warning -->
    <p
      v-if="delta.swing_warning"
      class="mt-1 inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-[10px] font-medium"
      :style="{
        color: 'var(--warning)',
        background: 'color-mix(in srgb, var(--warning) 10%, var(--surface))',
        border: '1px solid var(--warning)',
      }"
    >
      ⚠ swing important
    </p>
  </div>
</template>
