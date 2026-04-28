<script setup lang="ts">
import { computed } from 'vue'
import type { SourceQuota } from '../composables/useSourcesApi'

const props = withDefaults(
  defineProps<{
    quota: SourceQuota
    /** Compact = thinner bar without the per-key breakdown. */
    compact?: boolean
  }>(),
  { compact: false },
)

const fillColor = computed(() => {
  const p = props.quota.pct_used
  if (p >= 90) return 'var(--danger)'
  if (p >= 70) return 'var(--warning)'
  return 'var(--success)'
})

const periodLabel = computed(() => {
  // '2026-04' → 'avr 2026'  /  '2026-04-26' → '26 avr 2026'
  const months = ['janv', 'févr', 'mars', 'avr', 'mai', 'juin', 'juil', 'août', 'sept', 'oct', 'nov', 'déc']
  const parts = props.quota.period.split('-')
  if (parts.length < 2) return props.quota.period
  const y = parts[0]
  const m = months[Number(parts[1]) - 1] ?? parts[1]
  if (parts.length >= 3) return `${parts[2]} ${m} ${y}`
  return `${m} ${y}`
})

const windowLabel = computed(() =>
  props.quota.window === 'monthly' ? 'Quota mensuel' : 'Quota journalier',
)
</script>

<template>
  <div>
    <!-- Header line: window label + period + percentage -->
    <div class="mb-1.5 flex items-baseline justify-between gap-3">
      <p
        class="font-mono text-[10px] uppercase tracking-wider"
        style="color: var(--ink-500);"
      >
        {{ windowLabel }} · {{ periodLabel }}
      </p>
      <p class="font-mono text-xs font-medium tabular-nums" style="color: var(--ink);">
        {{ Math.round(quota.pct_used) }}%
      </p>
    </div>

    <!-- Bar -->
    <div
      class="overflow-hidden rounded-full"
      :style="{
        height: compact ? '6px' : '8px',
        background: 'var(--surface-2)',
      }"
    >
      <div
        class="h-full rounded-full transition-[width] duration-500 ease-out"
        :style="{
          width: `${Math.min(100, Math.max(0, quota.pct_used))}%`,
          background: fillColor,
        }"
      />
    </div>

    <!-- Calls breakdown -->
    <div
      v-if="!compact"
      class="mt-1.5 flex items-baseline justify-between gap-3"
    >
      <p class="font-mono text-xs tabular-nums" style="color: var(--ink);">
        {{ quota.calls.toLocaleString('fr-FR') }}
        <span class="opacity-60">/ {{ quota.limit.toLocaleString('fr-FR') }} calls</span>
      </p>
      <p class="font-mono text-xs tabular-nums" style="color: var(--ink-500);">
        {{ quota.remaining.toLocaleString('fr-FR') }} restants
      </p>
    </div>

    <!-- Per-key breakdown (Numista only) -->
    <div
      v-if="!compact && quota.per_key && quota.per_key.length > 0"
      class="mt-3 space-y-1 border-t pt-2.5"
      style="border-color: var(--surface-2);"
    >
      <p
        class="font-mono text-[10px] uppercase tracking-wider"
        style="color: var(--ink-500);"
      >
        Par clé ({{ quota.per_key.length }})
      </p>
      <div
        v-for="key in quota.per_key"
        :key="key.key_hash"
        class="flex items-center justify-between gap-3 text-xs"
      >
        <span class="font-mono" style="color: var(--ink-500);">
          slot {{ key.slot }} · …{{ key.key_hash.slice(-6) }}
        </span>
        <span class="font-mono tabular-nums" style="color: var(--ink);">
          {{ key.calls.toLocaleString('fr-FR') }}
          <span
            v-if="key.exhausted"
            class="ml-1 rounded-sm px-1 text-[10px] font-medium"
            style="background: var(--danger); color: var(--surface);"
          >
            exhausted
          </span>
        </span>
      </div>
    </div>
  </div>
</template>
