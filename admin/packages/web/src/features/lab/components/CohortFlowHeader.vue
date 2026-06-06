<script setup lang="ts">
// F3 — Frise du FLOW cohorte en tête de page : les 10 étapes qui transforment
// une cohorte en dataset de training, chacune avec un statut dérivé d'un
// compteur d'ÉTAT PERSISTÉ (image_state_current / funnel-status), aucune
// heuristique. Trois familles : Capture (hold-out, jamais train) · Sourcing+crop
// (eBay → training-eligible) · Entraînement. Cf. REBUILD-ANALYSIS.md §UX.

import { useCohortFunnelStatusQuery } from '@/features/lab/composables/useLabQueries'
import type { CohortFunnelCoin, CohortProgress, CohortSummary } from '@/features/lab/types'
import { computed } from 'vue'

const props = defineProps<{
  cohortId: string
  cohort: CohortSummary
  progress: CohortProgress | null
}>()

const funnelQuery = useCohortFunnelStatusQuery(() => props.cohortId)
const perCoin = computed<CohortFunnelCoin[]>(() => funnelQuery.data.value?.per_coin ?? [])
function sum(f: (c: CohortFunnelCoin) => number): number {
  return perCoin.value.reduce((a, c) => a + (f(c) || 0), 0)
}

type Status = 'done' | 'progress' | 'warn' | 'todo'

interface Step {
  n: number
  title: string
  sub: string
  status: Status
  detail: string
  group: 'capture' | 'sourcing' | 'train'
}

const steps = computed<Step[]>(() => {
  const pc = perCoin.value
  const nCoins = props.cohort.eurio_ids.length
  const c2 = props.progress?.c2
  const scrapable = pc.filter(c => c.scrapable)
  const scraped = scrapable.filter(c => c.n_source_images > 0).length
  const listings = sum(c => c.n_source_images)
  const downloaded = sum(c => c.n_downloaded)
  const dlFailed = sum(c => c.n_download_failed)
  const crops = sum(c => c.n_crops)
  const orphaned = sum(c => c.n_orphaned)
  const matched = sum(c => c.n_in_review + c.n_resolved + (c.state_counts?.auto_matched ?? 0))
  const inReview = sum(c => c.n_in_review)
  const validated = sum(c => c.n_resolved_training)
  const belowFloor = pc.filter(c => c.below_real_floor ?? !c.enough).length
  const iters = props.cohort.iteration_count

  return [
    { n: 1, title: 'Sélection', sub: 'pièces', group: 'capture',
      status: nCoins > 0 ? 'done' : 'todo', detail: `${nCoins} pièces` },
    { n: 2, title: 'Capture device', sub: 'hold-out / bench', group: 'capture',
      status: !c2 ? 'todo' : c2.fully_captured >= nCoins ? 'done' : c2.fully_captured > 0 ? 'warn' : 'todo',
      detail: c2 ? `${c2.fully_captured}/${nCoins}` : '—' },
    { n: 3, title: 'Scrape eBay', sub: 'par groupe', group: 'sourcing',
      status: scrapable.length === 0 ? 'todo' : scraped >= scrapable.length ? 'done' : scraped > 0 ? 'progress' : 'warn',
      detail: `${scraped}/${scrapable.length}` },
    { n: 4, title: 'Téléchargement', sub: 'images rapatriées', group: 'sourcing',
      status: listings === 0 ? 'todo' : dlFailed > 0 ? 'warn' : 'done',
      detail: fmt(downloaded) },
    { n: 5, title: 'Crop auto', sub: 'détection', group: 'sourcing',
      status: crops === 0 ? 'todo' : orphaned > 0 ? 'warn' : 'progress',
      detail: fmt(crops) },
    { n: 6, title: 'Theme matcher', sub: '→ eurio_id', group: 'sourcing',
      status: matched === 0 ? 'todo' : 'progress', detail: fmt(matched) },
    { n: 7, title: 'Tri lanes', sub: 'auto / LLM / manuel', group: 'sourcing',
      status: inReview > 0 ? 'progress' : crops > 0 ? 'done' : 'todo', detail: fmt(inReview) },
    { n: 8, title: 'Validés', sub: '→ training', group: 'sourcing',
      status: validated > 0 ? 'progress' : 'todo', detail: fmt(validated) },
    { n: 9, title: 'Enrichir', sub: '≥100 / classe', group: 'train',
      status: belowFloor > 0 ? 'warn' : pc.length > 0 ? 'done' : 'todo',
      detail: belowFloor > 0 ? `${belowFloor} sous plancher` : 'ok' },
    { n: 10, title: 'Run ArcFace', sub: 'vs captures', group: 'train',
      status: iters > 0 ? 'done' : 'todo', detail: iters > 0 ? `${iters} itér` : '—' },
  ]
})

function fmt(n: number): string {
  return n.toLocaleString('fr-FR')
}
const ICON: Record<Status, string> = { done: '✓', progress: '◐', warn: '⚠', todo: '—' }
</script>

<template>
  <section class="flow">
    <header class="flow__head">
      <h2 class="flow__title">Flow de la cohorte</h2>
      <p class="flow__lede">
        Comment une pièce passe de la sélection au benchmark. Chaque étage = un
        compteur d'état réel.
      </p>
      <span class="flow__legend">
        <span><b>✓</b> complet</span>
        <span><b>◐</b> en cours</span>
        <span style="color: var(--warning);"><b>⚠</b> attention</span>
        <span><b>—</b> pas démarré</span>
      </span>
    </header>

    <div class="flow__groups">
      <div class="flow__group flow__group--capture">
        <span class="flow__group-lbl">Capture · hold-out (jamais train)</span>
      </div>
      <div class="flow__group flow__group--sourcing">
        <span class="flow__group-lbl">Sourcing eBay + crop · auto + review</span>
      </div>
      <div class="flow__group flow__group--train">
        <span class="flow__group-lbl">Entraînement</span>
      </div>
    </div>

    <ol class="flow__steps">
      <li
        v-for="(s, i) in steps"
        :key="s.n"
        class="flow__step"
        :class="[`flow__step--${s.status}`, `flow__step--g-${s.group}`]"
      >
        <span class="flow__step-n">{{ s.n }}</span>
        <span class="flow__step-title">{{ s.title }}</span>
        <span class="flow__step-sub">{{ s.sub }}</span>
        <span class="flow__step-stat">
          <span class="flow__step-icon">{{ ICON[s.status] }}</span>
          <span class="flow__step-detail">{{ s.detail }}</span>
        </span>
        <span v-if="i < steps.length - 1" class="flow__step-arr">→</span>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.flow {
  margin-bottom: 24px;
  padding: 16px 18px 18px;
  border: 1px solid var(--surface-3);
  border-radius: 10px;
  background: color-mix(in srgb, var(--surface-1) 40%, var(--surface));
}
.flow__head { display: flex; align-items: baseline; flex-wrap: wrap; gap: 8px 16px; }
.flow__title {
  font-family: var(--font-display);
  font-style: italic;
  font-weight: 600;
  font-size: 18px;
  color: var(--ink);
  letter-spacing: -0.01em;
}
.flow__lede { font-size: 11.5px; color: var(--ink-400); }
.flow__legend {
  margin-left: auto;
  display: flex;
  gap: 12px;
  font-size: 10px;
  color: var(--ink-400);
}
.flow__legend b { font-style: normal; color: var(--ink-500); }

/* Bandeau des 3 familles, aligné en proportion sur les étapes (2 / 6 / 2). */
.flow__groups {
  margin-top: 14px;
  display: grid;
  grid-template-columns: 2fr 6fr 2fr;
  gap: 8px;
}
.flow__group {
  border-radius: 4px 4px 0 0;
  padding: 3px 8px;
  border-bottom: 2px solid;
}
.flow__group-lbl {
  font-family: var(--font-mono);
  font-size: 8.5px;
  text-transform: uppercase;
  letter-spacing: var(--tracking-eyebrow);
  white-space: nowrap;
}
.flow__group--capture { border-color: var(--gold-600); background: color-mix(in srgb, var(--gold-600) 6%, transparent); }
.flow__group--capture .flow__group-lbl { color: var(--gold-700); }
.flow__group--sourcing { border-color: var(--indigo-700); background: color-mix(in srgb, var(--indigo-700) 6%, transparent); }
.flow__group--sourcing .flow__group-lbl { color: var(--indigo-700); }
.flow__group--train { border-color: var(--ink-300); background: color-mix(in srgb, var(--ink-300) 8%, transparent); }
.flow__group--train .flow__group-lbl { color: var(--ink-500); }

.flow__steps {
  display: grid;
  grid-template-columns: repeat(10, 1fr);
  gap: 0;
  margin: 0;
  padding: 0;
  list-style: none;
}
.flow__step {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 10px 8px 10px 10px;
  border-top: 1px solid var(--surface-3);
  border-bottom: 1px solid var(--surface-3);
  border-right: 1px dashed var(--surface-2);
  background: var(--surface);
  min-width: 0;
}
.flow__step:first-child { border-left: 1px solid var(--surface-3); border-radius: 0 0 0 6px; }
.flow__step:last-child { border-right: 1px solid var(--surface-3); border-radius: 0 0 6px 0; }
.flow__step-n {
  font-family: var(--font-mono);
  font-size: 9px;
  color: var(--ink-300);
}
.flow__step-title {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--ink);
  line-height: 1.1;
}
.flow__step-sub {
  font-family: var(--font-mono);
  font-size: 8.5px;
  text-transform: uppercase;
  letter-spacing: var(--tracking-eyebrow);
  color: var(--ink-400);
  line-height: 1.2;
}
.flow__step-stat {
  margin-top: 4px;
  display: flex;
  align-items: baseline;
  gap: 5px;
}
.flow__step-icon { font-size: 13px; line-height: 1; }
.flow__step-detail {
  font-family: var(--font-mono);
  font-size: 10px;
  font-variant-numeric: tabular-nums;
  color: var(--ink-500);
}
.flow__step-arr {
  position: absolute;
  right: -6px;
  top: 50%;
  transform: translateY(-50%);
  z-index: 1;
  font-size: 12px;
  color: var(--ink-300);
  background: var(--surface);
  line-height: 1;
}

/* Statut par étape (icône + accent gauche) */
.flow__step--done .flow__step-icon { color: var(--success); }
.flow__step--progress .flow__step-icon { color: var(--indigo-700); }
.flow__step--warn { background: color-mix(in srgb, var(--warning) 6%, var(--surface)); }
.flow__step--warn .flow__step-icon { color: var(--warning); }
.flow__step--todo { opacity: 0.62; }
.flow__step--todo .flow__step-icon { color: var(--ink-300); }

@media (max-width: 900px) {
  .flow__steps { grid-template-columns: repeat(5, 1fr); }
  .flow__step:nth-child(5) { border-right: 1px solid var(--surface-3); }
  .flow__groups { display: none; }
}
</style>
