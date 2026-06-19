<script setup lang="ts">
import { AlertTriangle } from 'lucide-vue-next'
import type { SearchFunnel } from '../composables/useBenchApi'

defineProps<{
  searches: SearchFunnel[]
  selectedYear: number | null
}>()
const emit = defineEmits<{ select: [year: number] }>()

function autoCount(s: SearchFunnel): number {
  return s.branches
    .filter(b => b.kind === 'auto')
    .reduce((n, b) => n + b.listings.length, 0)
}
</script>

<template>
  <div class="grid gap-2.5" :style="`grid-template-columns: repeat(${searches.length}, 1fr);`">
    <button
      v-for="s in searches"
      :key="s.year"
      class="group relative overflow-hidden rounded-xl border px-4 py-3 text-left transition-all"
      :style="selectedYear === s.year
        ? 'border-color: var(--indigo-600); background: var(--surface); box-shadow: 0 1px 0 var(--indigo-600), 0 6px 16px -10px var(--indigo-900);'
        : 'border-color: var(--surface-3); background: var(--surface-1);'"
      @click="emit('select', s.year)"
    >
      <div class="flex items-start justify-between">
        <div>
          <div
            class="text-[26px] leading-none"
            :style="`font-family: var(--font-display); font-weight: 600; color: ${
              selectedYear === s.year ? 'var(--indigo-700)' : 'var(--ink)'};`"
          >{{ s.year }}</div>
          <div
            class="mt-0.5 text-[10.5px] uppercase tracking-[0.08em]"
            style="color: var(--ink-400); font-family: var(--font-mono);"
          >{{ s.country }} · {{ s.denomination }}</div>
        </div>
        <span
          v-if="s.nDisagreements > 0"
          class="flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[10px] font-semibold"
          style="background: var(--danger-soft, #f6dcd6); color: var(--danger);"
        >
          <AlertTriangle class="h-2.5 w-2.5" />
          {{ s.nDisagreements }}
        </span>
      </div>

      <!-- eurio_ids visés par cette recherche -->
      <div class="mt-2.5 flex flex-wrap gap-1">
        <span
          v-for="c in s.coins"
          :key="c.eurio_id"
          class="truncate rounded px-1.5 py-0.5 text-[10px]"
          style="background: var(--surface-2); color: var(--ink-500); font-family: var(--font-mono); max-width: 100%;"
        >{{ c.eurio_id.replace(/^[a-z]{2}-\d{4}-2eur-/, '') }}</span>
      </div>

      <!-- Mini-bilan : brut → auto -->
      <div
        class="mt-2.5 flex items-center gap-1 text-[11px]"
        style="color: var(--ink-400);"
      >
        <span style="font-family: var(--font-mono);">{{ s.total }}</span>
        <span>brut</span>
        <span style="color: var(--ink-300);">→</span>
        <span style="font-family: var(--font-mono); color: var(--indigo-700);">
          {{ autoCount(s) }}
        </span>
        <span>auto</span>
      </div>
    </button>
  </div>
</template>
