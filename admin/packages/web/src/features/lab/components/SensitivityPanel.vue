<script setup lang="ts">
import type { SensitivityEntry } from '../types'

defineProps<{
  entries: SensitivityEntry[]
}>()

function shortPath(p: string): string {
  return p.replace(/^recipe\./, '').replace(/^training_config\./, '')
}

function deltaColor(v: number): string {
  if (v > 0.005) return 'var(--success)'
  if (v < -0.005) return 'var(--danger)'
  return 'var(--ink-400)'
}

function formatPts(v: number): string {
  const sign = v > 0 ? '+' : ''
  return `${sign}${(v * 100).toFixed(2)} pts`
}
</script>

<template>
  <div
    class="rounded-lg border"
    style="border-color: var(--surface-3); background: var(--surface);"
  >
    <div class="border-b px-4 py-3" style="border-color: var(--surface-3);">
      <p class="font-display italic text-sm" style="color: var(--indigo-700);">
        Sensibilité des paramètres
      </p>
      <p class="mt-1 text-[10px]" style="color: var(--ink-500);">
        Delta R@1 moyen observé quand ce paramètre a changé entre parent → itération.
      </p>
    </div>
    <div v-if="entries.length === 0" class="px-4 py-6 text-center text-xs italic" style="color: var(--ink-400);">
      Pas encore assez d'itérations chaînées pour agréger des leviers.
    </div>
    <table v-else class="w-full text-xs">
      <thead>
        <tr class="border-b" style="border-color: var(--surface-3);">
          <th class="px-4 py-2 text-left text-[10px] uppercase" style="color: var(--ink-500);">Paramètre</th>
          <th class="px-4 py-2 text-right text-[10px] uppercase" style="color: var(--ink-500);">Obs.</th>
          <th class="px-4 py-2 text-right text-[10px] uppercase" style="color: var(--ink-500);">ΔR@1 moyen</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="e in entries"
          :key="e.path"
          class="border-b last:border-b-0"
          style="border-color: var(--surface-3);"
        >
          <td class="px-4 py-1.5 font-mono" style="color: var(--ink);">
            {{ shortPath(e.path) }}
          </td>
          <td class="px-4 py-1.5 text-right font-mono tabular-nums" style="color: var(--ink-500);">
            {{ e.observations }}
          </td>
          <td
            class="px-4 py-1.5 text-right font-mono tabular-nums"
            :style="{ color: deltaColor(e.avg_delta_r1) }"
          >
            {{ formatPts(e.avg_delta_r1) }}
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
