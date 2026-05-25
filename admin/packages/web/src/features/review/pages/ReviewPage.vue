<script setup lang="ts">
// Shell de la page /review (refactoré Phase 2 R.0 — 2026-05-04).
// Contient : titre, toggle Single | Lot, mount de la bonne vue.
// Le mode est persisté via le query param `?mode=` (atterrissage
// depuis le breakdown de run pourra forcer mode=lot directement).
//
// Cf. docs/sources-refacto/lot-review-kickoff.md §L-D-5.

import { computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Layers, Package } from 'lucide-vue-next'
import SingleReviewView from '../views/SingleReviewView.vue'
import LotReviewView from '../views/LotReviewView.vue'

type ReviewMode = 'single' | 'lot'

const route = useRoute()
const router = useRouter()

const mode = computed<ReviewMode>(() => {
  const m = route.query.mode
  return m === 'lot' ? 'lot' : 'single'
})

function setMode(next: ReviewMode) {
  if (mode.value === next) return
  void router.replace({
    query: { ...route.query, mode: next === 'single' ? undefined : next },
  })
}

function backToCabinet() {
  void router.push('/review')
}

// Reset focus state on mode swap if needed (currently each view is
// fully self-contained, so nothing extra to do).
watch(mode, () => {})
</script>

<template>
  <div class="flex h-full flex-col">
    <!-- ═══ Top bar : titre + toggle ═══ -->
    <header
      class="flex flex-wrap items-center justify-between gap-4 border-b px-8 py-3"
      style="border-color: var(--surface-3); background: var(--surface);"
    >
      <div class="flex items-center gap-4">
        <button
          type="button"
          class="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px] font-mono uppercase tracking-wider transition-colors"
          style="border-color: var(--surface-3); color: var(--ink-500); background: var(--surface-1);"
          @click="backToCabinet"
        >
          <ArrowLeft class="h-3 w-3" />
          Cabinet
        </button>
        <div>
          <h1
            class="font-display text-lg italic font-semibold"
            style="color: var(--indigo-700);"
          >
            Review queue
          </h1>
          <p class="mt-0.5 text-xs" style="color: var(--ink-500);">
            Résolution humaine des images non auto-matchées
          </p>
        </div>
      </div>

      <!-- Toggle Single | Lot -->
      <div
        class="inline-flex rounded-md border p-0.5"
        style="border-color: var(--surface-3); background: var(--surface-1);"
        role="tablist"
      >
        <button
          type="button"
          role="tab"
          :aria-selected="mode === 'single'"
          class="inline-flex items-center gap-1.5 rounded-[5px] px-3 py-1 font-mono text-[11px] uppercase tracking-wider transition-colors"
          :style="{
            background: mode === 'single' ? 'var(--surface)' : 'transparent',
            color: mode === 'single' ? 'var(--indigo-700)' : 'var(--ink-500)',
            boxShadow: mode === 'single' ? '0 1px 2px rgba(14,14,31,.06)' : 'none',
          }"
          @click="setMode('single')"
        >
          <Layers class="h-3 w-3" />
          Single
        </button>
        <button
          type="button"
          role="tab"
          :aria-selected="mode === 'lot'"
          class="inline-flex items-center gap-1.5 rounded-[5px] px-3 py-1 font-mono text-[11px] uppercase tracking-wider transition-colors"
          :style="{
            background: mode === 'lot' ? 'var(--surface)' : 'transparent',
            color: mode === 'lot' ? 'var(--gold-600)' : 'var(--ink-500)',
            boxShadow: mode === 'lot' ? '0 1px 2px rgba(14,14,31,.06)' : 'none',
          }"
          @click="setMode('lot')"
        >
          <Package class="h-3 w-3" />
          Lot
        </button>
      </div>
    </header>

    <!-- ═══ Vue mountée selon le mode ═══ -->
    <SingleReviewView v-if="mode === 'single'" />
    <LotReviewView v-else />
  </div>
</template>
