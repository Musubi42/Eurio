<script setup lang="ts">
import { CornerDownLeft } from 'lucide-vue-next'
import type { ReviewFace } from '../composables/useReviewApi'

defineProps<{
  face: ReviewFace
  canValidate: boolean
  focusedEurioId: string | null
  // Raison du blocage quand canValidate est faux (tooltip + ligne d'aide).
  validateHint?: string | null
}>()

defineEmits<{
  (e: 'face', value: ReviewFace): void
  (e: 'validate'): void
  (e: 'reject'): void
  (e: 'skip'): void
}>()

const FACE_ITEMS: { key: ReviewFace; label: string; hint: string }[] = [
  { key: 'obverse', label: 'Avers', hint: 'O' },
  { key: 'reverse', label: 'Revers', hint: 'V' },
  { key: 'unknown', label: 'Inconnu', hint: 'U' },
]
</script>

<template>
  <div
    class="sticky bottom-0 z-10 flex flex-wrap items-center justify-between gap-4 border-t px-6 py-3"
    style="border-color: var(--surface-3); background: color-mix(in srgb, var(--surface) 96%, transparent); backdrop-filter: blur(6px);"
  >
    <!-- Face radio -->
    <div class="flex items-center gap-3">
      <span
        class="font-mono text-[10px] uppercase tracking-wider"
        style="color: var(--ink-500);"
      >
        Face
      </span>
      <div class="inline-flex rounded-md border" style="border-color: var(--surface-3);">
        <button
          v-for="opt in FACE_ITEMS"
          :key="opt.key"
          type="button"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 text-[12px] transition-colors"
          :style="{
            background: face === opt.key ? 'var(--indigo-700)' : 'var(--surface)',
            color: face === opt.key ? 'var(--surface)' : 'var(--ink-700)',
          }"
          @click="$emit('face', opt.key)"
        >
          {{ opt.label }}
          <span
            class="font-mono text-[9px] uppercase tracking-wider"
            :style="{ color: face === opt.key ? 'var(--gold-soft)' : 'var(--ink-400)' }"
          >
            {{ opt.hint }}
          </span>
        </button>
      </div>
    </div>

    <!-- Actions principales -->
    <div class="flex items-center gap-2">
      <span
        v-if="!canValidate && validateHint"
        class="mr-1 text-[10px] italic"
        style="color: var(--ink-400);"
      >
        {{ validateHint }}
      </span>
      <button
        type="button"
        class="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[12px] transition-all"
        style="background: var(--surface-1); color: var(--ink-700); border: 1px solid var(--surface-3);"
        @click="$emit('skip')"
      >
        Skip
        <span class="font-mono text-[9px] uppercase tracking-wider opacity-60">N</span>
      </button>

      <button
        type="button"
        class="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-[12px] font-medium transition-all"
        :style="{
          borderColor: 'var(--danger)',
          color: 'var(--danger)',
          background: 'color-mix(in srgb, var(--danger) 6%, var(--surface))',
        }"
        @click="$emit('reject')"
      >
        Reject
        <span class="font-mono text-[9px] uppercase tracking-wider opacity-70">R</span>
      </button>

      <button
        type="button"
        class="inline-flex items-center gap-2 rounded-md px-4 py-1.5 text-[13px] font-semibold transition-all"
        :disabled="!canValidate"
        :style="{
          background: canValidate ? 'var(--indigo-700)' : 'var(--surface-2)',
          color: canValidate ? 'var(--surface)' : 'var(--ink-400)',
          cursor: canValidate ? 'pointer' : 'not-allowed',
        }"
        :title="canValidate ? `Valider avec ${focusedEurioId}` : (validateHint ?? 'Sélection requise')"
        @click="$emit('validate')"
      >
        Validate
        <CornerDownLeft class="h-3.5 w-3.5" />
      </button>
    </div>
  </div>
</template>
