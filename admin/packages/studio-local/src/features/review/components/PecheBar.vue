<script setup lang="ts">
// La barre de pêche — le périmètre, en clair, au-dessus de la file.
//
// Elle dit trois choses et n'en cache aucune :
//   · ce qu'on pêche (la classe, et sous quelles étiquettes la banque l'indexe) ;
//   · combien il y a à voir, PAR MODE — le stock d'une file n'est pas celui de
//     l'autre, et un seul nombre pour les deux ferait mentir le bouton ;
//   · ce qui est hors file (`n_orphans`) — le stock qu'on ne voit nulle part
//     ailleurs, donc celui qu'un écran ne doit surtout pas taire.
//
// Elle ne coche rien. À 0,10 de marge, un standard sur vingt est faux : le
// filet propose, l'humain tranche.

import { computed } from 'vue'
import { Loader2 } from 'lucide-vue-next'
import type { DinoCandidatesSummary } from '../composables/useReviewApi'

const props = defineProps<{
  classId: string
  rank: number
  minSpread: number | null
  mode: 'single' | 'lot'
  summary: DinoCandidatesSummary | null
  loading: boolean
  enqueuing: boolean
}>()

const emit = defineEmits<{
  (e: 'rank', value: number): void
  (e: 'min-spread', value: number | null): void
  (e: 'mode', value: 'single' | 'lot'): void
  (e: 'enqueue-orphans'): void
}>()

const RANKS = [1, 3, 5]
/** Les paliers de marge, avec la précision mesurée le 2026-08-20 en regard. */
const SPREADS: { value: number | null; label: string; hint: string }[] = [
  { value: null, label: 'toutes', hint: 'Aucun filtre de marge — la précision du top-1 tombe à ~84 % sur une pièce courante.' },
  { value: 0.05, label: '≥ 0,05', hint: 'Le seuil du verdict. ~86 % de précision sur une courante, ~95 % sur une commémorative.' },
  { value: 0.10, label: '≥ 0,10', hint: 'Le palier d’auto-acceptation. 95,4 % sur une courante (n=217), 99,9 % sur une commémorative (n=1352).' },
]

const nSingle = computed(() => props.summary?.n_open_single ?? null)
const nLot = computed(() => props.summary?.n_open_lot ?? null)
const nOrphans = computed(() => props.summary?.n_orphans ?? 0)
</script>

<template>
  <div class="bar">
    <span class="bar__lbl">pêche</span>

    <div class="bar__id">
      <span class="bar__cls">{{ classId || '—' }}</span>
      <span
        v-if="summary && summary.bank_class_ids.length"
        class="bar__bank"
        :title="`La banque indexe cette classe sous : ${summary.bank_class_ids.join(', ')}. Une pièce courante y est rangée sous le plus ancien millésime de son ère, pas sous son propre identifiant.`"
      >{{ summary.bank_class_ids.length }} étiquette<span v-if="summary.bank_class_ids.length > 1">s</span> de banque</span>
    </div>

    <span class="stock">
      <button
        type="button" class="chip" :class="{ 'chip--on': mode === 'single' }"
        :disabled="nSingle === 0" @click="emit('mode', 'single')"
      >{{ nSingle ?? '…' }} à l'unité</button>
      <button
        type="button" class="chip" :class="{ 'chip--on': mode === 'lot' }"
        :disabled="nLot === 0" @click="emit('mode', 'lot')"
      >{{ nLot ?? '…' }} en lots</button>
    </span>

    <span class="ranks" title="Jusqu'où descendre dans les hypothèses du modèle. Top 1 = sa première réponse. Top 3 / Top 5 élargissent le filet quand la classe est affamée, au prix de plus de faux à écarter à l'œil.">
      <button
        v-for="r in RANKS" :key="r" type="button"
        class="chip chip--rank" :class="{ 'chip--on': rank === r }"
        @click="emit('rank', r)"
      >Top {{ r }}</button>
    </span>

    <span class="ranks">
      <button
        v-for="s in SPREADS" :key="String(s.value)" type="button"
        class="chip chip--rank" :class="{ 'chip--on': minSpread === s.value }"
        :title="s.hint" @click="emit('min-spread', s.value)"
      >{{ s.label }}</button>
    </span>

    <Loader2 v-if="loading" class="h-3.5 w-3.5 animate-spin" style="color: var(--ink-400);" />

    <button
      v-if="nOrphans > 0"
      type="button"
      class="chip chip--orphan"
      :disabled="enqueuing"
      :title="`${nOrphans} crop(s) que la banque rattache à cette classe n'ont AUCUNE ligne de review ouverte : ils ne sont dans aucune file, donc invisibles partout. Les enfiler les rend tranchables — c'est une écriture, elle ne se fait que sur ce clic.`"
      @click="emit('enqueue-orphans')"
    >
      <Loader2 v-if="enqueuing" class="h-3 w-3 animate-spin" />
      ⚠ {{ nOrphans }} hors file — enfiler
    </button>

    <span class="bar__note">
      Une suggestion, pas un verdict : à marge ≥ 0,10, environ un standard sur
      vingt est faux.
    </span>
  </div>
</template>

<style scoped>
.bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 9px 18px;
  border-bottom: 1px solid var(--surface-3);
  background: var(--surface);
}
.bar__lbl {
  font-family: var(--font-mono);
  font-size: 9.5px;
  text-transform: uppercase;
  letter-spacing: var(--tracking-eyebrow);
  color: var(--ink-400);
}
.bar__id { display: flex; flex-direction: column; min-width: 0; }
.bar__cls { font-size: 13px; font-weight: 500; color: var(--ink); }
.bar__bank { font-family: var(--font-mono); font-size: 9.5px; color: var(--ink-400); cursor: help; }
.bar__note {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 9.5px;
  color: var(--ink-400);
  max-width: 34ch;
  line-height: 1.35;
}
.stock, .ranks { display: inline-flex; gap: 4px; }
.chip {
  font-family: var(--font-mono);
  font-size: 10.5px;
  padding: 4px 9px;
  border-radius: 999px;
  border: 1px solid var(--surface-3);
  background: var(--surface-1);
  color: var(--ink-600);
  cursor: pointer;
}
.chip--on { border-color: var(--indigo-700); color: var(--indigo-700); background: color-mix(in srgb, var(--indigo-700) 8%, var(--surface)); }
.chip--rank { padding-inline: 7px; }
.chip--orphan {
  display: inline-flex; align-items: center; gap: 5px;
  border-color: var(--warning); color: var(--warning);
}
.chip:disabled { opacity: 0.4; cursor: not-allowed; }
.chip:focus-visible { outline: 2px solid var(--gold); outline-offset: 1px; }
</style>
