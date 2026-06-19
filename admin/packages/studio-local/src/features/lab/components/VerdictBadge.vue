<script setup lang="ts">
import type { Verdict } from '../types'
import { computed } from 'vue'

const props = defineProps<{
  verdict: Verdict | null | undefined
  override?: Verdict | null | undefined
  compact?: boolean
}>()

const resolved = computed<Verdict>(() => (props.override ?? props.verdict ?? 'pending') as Verdict)

const tint = computed(() => {
  const v = resolved.value
  if (v === 'better') return 'var(--success)'
  if (v === 'worse') return 'var(--danger)'
  if (v === 'mixed') return 'var(--warning)'
  if (v === 'baseline') return 'var(--indigo-700)'
  return 'var(--ink-400)'
})

const label = computed(() => {
  const v = resolved.value
  if (v === 'pending') return 'en attente'
  return v
})
</script>

<template>
  <span
    class="inline-flex items-center gap-1 rounded-full font-medium"
    :class="props.compact ? 'px-1.5 py-0.5 text-[10px]' : 'px-2 py-0.5 text-xs'"
    :style="{
      background: `color-mix(in srgb, ${tint} 14%, var(--surface))`,
      color: tint,
      border: `1px solid color-mix(in srgb, ${tint} 28%, transparent)`,
    }"
    :title="props.override ? `override: ${resolved}` : resolved"
  >
    <span v-if="props.override" class="text-[8px] opacity-60">✎</span>
    {{ label }}
  </span>
</template>
