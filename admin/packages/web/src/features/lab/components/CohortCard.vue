<script setup lang="ts">
import type { CohortSummary } from '../types'

defineProps<{ cohort: CohortSummary }>()

function zoneColor(zone: string | null): string {
  if (zone === 'green') return 'var(--success)'
  if (zone === 'orange') return 'var(--warning)'
  if (zone === 'red') return 'var(--danger)'
  return 'var(--ink-400)'
}

function formatPct(v: number | null): string {
  if (v == null) return '—'
  return `${(v * 100).toFixed(1)}%`
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('fr-FR', {
    day: 'numeric', month: 'short',
  })
}
</script>

<template>
  <article
    class="group relative cursor-pointer overflow-hidden rounded-lg border p-5 transition-all"
    style="
      border-color: var(--surface-3);
      background: var(--surface);
      box-shadow: var(--shadow-sm);
    "
  >
    <header class="flex items-start justify-between gap-4">
      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-2">
          <h3
            class="font-display text-lg italic font-semibold"
            style="color: var(--indigo-700);"
          >
            {{ cohort.name }}
          </h3>
          <span
            v-if="cohort.zone"
            class="rounded-full px-2 py-0.5 text-[10px] font-medium"
            :style="{
              background: `color-mix(in srgb, ${zoneColor(cohort.zone)} 14%, var(--surface))`,
              color: zoneColor(cohort.zone),
            }"
          >
            {{ cohort.zone }}
          </span>
        </div>
        <p
          v-if="cohort.description"
          class="mt-1 line-clamp-2 text-xs"
          style="color: var(--ink-500);"
        >
          {{ cohort.description }}
        </p>
      </div>
    </header>

    <div class="mt-4 grid grid-cols-3 gap-3 text-xs">
      <div>
        <p class="text-[10px] uppercase" style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
          Pièces
        </p>
        <p class="mt-1 font-mono tabular-nums" style="color: var(--ink);">
          {{ cohort.eurio_ids.length }}
        </p>
      </div>
      <div>
        <p class="text-[10px] uppercase" style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
          Itérations
        </p>
        <p class="mt-1 font-mono tabular-nums" style="color: var(--ink);">
          {{ cohort.iteration_count }}
        </p>
      </div>
      <div>
        <p class="text-[10px] uppercase" style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
          Best R@1
        </p>
        <p
          class="mt-1 font-mono tabular-nums"
          :style="{ color: cohort.best_r_at_1 != null ? 'var(--success)' : 'var(--ink-400)' }"
        >
          {{ formatPct(cohort.best_r_at_1) }}
        </p>
      </div>
    </div>

    <footer class="mt-4 flex items-center justify-between text-[10px]" style="color: var(--ink-400);">
      <span>créé {{ formatDate(cohort.created_at) }}</span>
      <span class="font-mono">{{ cohort.id }}</span>
    </footer>
  </article>
</template>
