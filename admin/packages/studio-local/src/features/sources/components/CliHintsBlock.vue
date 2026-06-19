<script setup lang="ts">
import { ref } from 'vue'
import { Check, ChevronRight, Copy, Play } from 'lucide-vue-next'
import type { CliHint, CliHintKind } from '../composables/useSourcesApi'

defineProps<{ hints: CliHint[] }>()

// Track per-command "Copied" feedback for 2s after click
const copiedKey = ref<string | null>(null)
let copiedTimeout: ReturnType<typeof setTimeout> | null = null

async function copyCommand(hint: CliHint) {
  try {
    await navigator.clipboard.writeText(hint.command)
    copiedKey.value = hint.command
    if (copiedTimeout) clearTimeout(copiedTimeout)
    copiedTimeout = setTimeout(() => {
      copiedKey.value = null
    }, 2000)
  } catch {
    // Clipboard refused (e.g. non-secure context) — silently no-op
  }
}

const KIND_GLYPH: Record<CliHintKind, string> = {
  run: '▶',
  'dry-run': '◇',
  list: '≡',
  status: '◉',
  reset: '↺',
}

const KIND_TONE: Record<CliHintKind, string> = {
  run: 'var(--indigo-700)',
  'dry-run': 'var(--ink-500)',
  list: 'var(--ink-500)',
  status: 'var(--ink-500)',
  reset: 'var(--warning)',
}
</script>

<template>
  <div>
    <div class="flex items-center gap-2 px-4 py-2.5"
         style="background: color-mix(in srgb, var(--surface-1) 60%, var(--surface));">
      <ChevronRight class="h-3 w-3" style="color: var(--ink-500);" />
      <p class="font-mono text-[10px] uppercase tracking-wider"
         style="color: var(--ink-500);">
        Commandes CLI ({{ hints.length }})
      </p>
    </div>

    <div>
      <div
        v-for="(hint, idx) in hints"
        :key="hint.command"
        class="px-4 py-3"
        :class="idx > 0 ? 'border-t' : ''"
        style="border-color: var(--surface-2);"
      >
        <!-- Title row -->
        <div class="mb-1.5 flex items-center justify-between gap-3">
          <div class="flex items-center gap-2">
            <span
              class="inline-flex h-4 w-4 items-center justify-center font-mono text-[11px]"
              :style="{ color: KIND_TONE[hint.kind] }"
            >
              {{ KIND_GLYPH[hint.kind] }}
            </span>
            <p class="text-sm font-medium" style="color: var(--ink);">
              {{ hint.title }}
            </p>
          </div>
          <button
            class="group inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px] font-medium transition-colors"
            :style="copiedKey === hint.command
              ? 'border-color: var(--success); color: var(--success); background: color-mix(in srgb, var(--success) 6%, var(--surface));'
              : 'border-color: var(--surface-3); color: var(--ink-500); background: var(--surface);'"
            @click="copyCommand(hint)"
          >
            <Check v-if="copiedKey === hint.command" class="h-3 w-3" />
            <Copy v-else class="h-3 w-3" />
            {{ copiedKey === hint.command ? 'Copié' : 'Copier' }}
          </button>
        </div>

        <!-- Command -->
        <code
          class="mb-1.5 block rounded-sm px-2 py-1 font-mono text-[11px] leading-snug"
          style="background: var(--surface-1); color: var(--ink); border: 1px solid var(--surface-2);"
        >{{ hint.command }}</code>

        <!-- Description -->
        <p class="text-[11px] leading-snug" style="color: var(--ink-500);">
          {{ hint.description }}
        </p>

        <!-- Outcome -->
        <p class="mt-0.5 text-[11px] leading-snug" style="color: var(--ink-500);">
          <span class="font-medium" style="color: var(--ink-400);">→</span>
          {{ hint.expected_outcome }}
        </p>
      </div>
    </div>

    <!-- V2 hint -->
    <div
      class="border-t px-4 py-2 text-[10px] italic"
      style="border-color: var(--surface-2); color: var(--ink-400); background: color-mix(in srgb, var(--surface-1) 30%, var(--surface));"
    >
      <Play class="mr-1 inline-block h-2.5 w-2.5" />
      V2 : un bouton "Lancer" remplacera "Copier" sur chaque commande.
    </div>
  </div>
</template>
