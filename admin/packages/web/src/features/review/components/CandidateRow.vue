<script setup lang="ts">
import type { ReviewCandidate } from '../composables/useReviewApi'

defineProps<{
  candidate: ReviewCandidate
  index: number
  focused: boolean
}>()

defineEmits<{
  (e: 'focus'): void
}>()
</script>

<template>
  <button
    type="button"
    class="flex w-full items-stretch gap-3 rounded-md border px-3 py-2 text-left transition-all"
    :style="{
      borderColor: focused ? 'var(--indigo-700)' : 'var(--surface-3)',
      background: focused
        ? 'color-mix(in srgb, var(--indigo-700) 6%, var(--surface))'
        : 'var(--surface)',
      boxShadow: focused ? '0 0 0 3px color-mix(in srgb, var(--indigo-700) 14%, transparent)' : 'none',
    }"
    @click="$emit('focus')"
  >
    <!-- Numero raccourci -->
    <span
      class="flex h-7 w-7 shrink-0 items-center justify-center rounded-md font-mono text-[11px] font-semibold"
      :style="{
        background: focused ? 'var(--indigo-700)' : 'var(--surface-1)',
        color: focused ? 'var(--surface)' : 'var(--ink-500)',
      }"
    >
      {{ index + 1 }}
    </span>

    <!-- Thumb canonique -->
    <img
      :src="candidate.canonical_thumb_url"
      :alt="candidate.eurio_id"
      class="h-12 w-12 shrink-0 rounded-md object-cover"
      style="background: var(--surface-1);"
    />

    <!-- Identité + score -->
    <div class="min-w-0 flex-1">
      <p class="truncate font-mono text-[12px] font-medium" style="color: var(--ink);">
        {{ candidate.eurio_id }}
      </p>
      <p class="mt-0.5 truncate text-[11px]" style="color: var(--ink-500);">
        {{ candidate.label }}
      </p>
    </div>

    <!-- Score -->
    <div class="shrink-0 text-right">
      <p
        class="font-mono text-[14px] font-semibold tabular-nums"
        :style="{
          color: candidate.score >= 0.75
            ? 'var(--success)'
            : candidate.score >= 0.5
              ? 'var(--gold-600)'
              : 'var(--ink-400)',
        }"
      >
        {{ candidate.score.toFixed(2) }}
      </p>
      <p class="font-mono text-[9px] uppercase tracking-wider" style="color: var(--ink-400);">
        score
      </p>
    </div>
  </button>
</template>
