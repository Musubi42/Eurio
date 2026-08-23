<script setup lang="ts">
// Shell de la page /review (refactoré Phase 2 R.0 — 2026-05-04).
// Contient : titre, toggle Single | Lot, mount de la bonne vue.
// Le mode est persisté via le query param `?mode=` (atterrissage
// depuis le breakdown de run pourra forcer mode=lot directement).
//
// Cf. docs/sources-refacto/lot-review-kickoff.md §L-D-5.

import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Layers, Package } from 'lucide-vue-next'
import { useCohortsQuery } from '@/features/lab/composables/useLabQueries'
import SingleReviewView from '../views/SingleReviewView.vue'
import LotReviewView from '../views/LotReviewView.vue'
import RunProgressLine from '../components/RunProgressLine.vue'
import { queryNeedOnly, queryRunIds } from '../composables/useQueryScope'
import { useEurioSession } from '@/stores/eurio-session'

type ReviewMode = 'single' | 'lot'

const route = useRoute()
const router = useRouter()
const session = useEurioSession()

// Axe DROIT (lot 5) — à ne pas confondre avec `hasLocalMlApi`, qui est l'axe
// MACHINE. Ici : « cette personne a-t-elle le droit ? ». Un ami invité (rôle
// `reviewer`) ne voit pas les gestes qui structurent le travail des autres.
const canArbitrate = computed(() => session.hasScope('review:arbitrate'))

const mode = computed<ReviewMode>(() => {
  const m = route.query.mode
  return m === 'lot' ? 'lot' : 'single'
})

// Optional cohort scope (Single mode) — persisted in the URL so it survives
// reloads and the queue view reads it from `?cohort=`.
const cohortsQuery = useCohortsQuery()
const cohorts = computed(() => cohortsQuery.data.value ?? [])
const selectedCohort = computed<string>(() =>
  typeof route.query.cohort === 'string' ? route.query.cohort : '',
)
function setCohort(id: string) {
  void router.replace({ query: { ...route.query, cohort: id || undefined } })
}

// Périmètre par run (`?run=a,b`) : la file — single comme lot — ne sert que
// les crops de ces runs, et un bandeau dit où on en est. Le param voyage avec
// le reste de la query (tous les `router.replace` ci-dessous la spreadent),
// donc un changement de mode ou une navigation de lot le garde.
const runIds = computed(() => queryRunIds(route) ?? [])
// `?need=1` : le compteur doit lire le même filtre que la file, sinon il
// annonce des ouverts que la file ne servira jamais (classes pleines, D2).
const needOnly = computed(() => queryNeedOnly(route))
const progressKey = ref(0)
function onDecided() { progressKey.value++ }

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

      <div class="flex items-center gap-3">
        <!-- Cohort scope (Single mode) — cadrer la file sur une cohorte est un
             geste de pilotage : masqué pour un ami invité (lot 5). -->
        <label
          v-if="mode === 'single' && canArbitrate"
          class="flex items-center gap-1.5 text-[11px] uppercase tracking-wider"
          style="color: var(--ink-500);"
        >
          Cohort
          <select
            class="rounded-md border px-2 py-1 text-xs font-mono normal-case"
            style="border-color: var(--surface-3); background: var(--surface-1); color: var(--ink);"
            :value="selectedCohort"
            @change="setCohort(($event.target as HTMLSelectElement).value)"
          >
            <option value="">Toutes</option>
            <option v-for="c in cohorts" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
        </label>

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
      </div>
    </header>

    <!-- ═══ Avancement par run (seulement quand ?run= est posé) ═══ -->
    <RunProgressLine
      v-if="runIds.length"
      :run-ids="runIds"
      :need-only="needOnly"
      :refresh-key="progressKey"
    />

    <!-- ═══ Vue mountée selon le mode ═══ -->
    <SingleReviewView v-if="mode === 'single'" @decided="onDecided" />
    <LotReviewView v-else />
  </div>
</template>
