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
  /** Filtre « annonce du pays de la classe » — actif par défaut. */
  countryOnly: boolean
  summary: DinoCandidatesSummary | null
  loading: boolean
  enqueuing: boolean
}>()

const emit = defineEmits<{
  (e: 'rank', value: number): void
  (e: 'min-spread', value: number | null): void
  (e: 'mode', value: 'single' | 'lot'): void
  (e: 'country-only', value: boolean): void
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

/** « 4 à l'unité » ne dit pas si ça vaut le coup de regarder. La meilleure
 *  marge, si. Vécu : quatre annonces FRANÇAISES à 0,023 au mieux dans la file
 *  d'une classe espagnole — quatre skips, et l'impression d'un écran cassé. */
function margeLabel(best: number | null | undefined): string {
  if (best == null) return ''
  return ` · marge max ${best.toFixed(3)}`
}
function margeTitle(best: number | null | undefined, n: number | null): string {
  if (best == null || !n) return 'Aucun candidat dans cette file.'
  if (best >= 0.10) return `Meilleure marge ${best.toFixed(3)} — au-dessus du palier d'auto-acceptation : le modèle est net sur au moins un crop.`
  if (best >= 0.05) return `Meilleure marge ${best.toFixed(3)} — au-dessus du seuil du verdict, sans plus. À l'œil.`
  return `Meilleure marge ${best.toFixed(3)} — SOUS le seuil du verdict (0,05). Le modèle n'est net sur AUCUN crop de cette file : ce sont probablement des faux positifs, ou des pièces que la banque ne connaît pas (une piécette de coffret, par exemple). Regarde l'autre mode, ou élargis le rang.`
}
/** O4c — le back a-t-il retiré le filtre pays parce qu'il ne laissait rien ?
 *  On le lit du SUMMARY, jamais de l'URL : `?pays=` dit ce qu'on a DEMANDÉ,
 *  le summary dit ce qui a été SERVI. Afficher la demande au-dessus d'une file
 *  qui n'y obéit pas, c'est le filtre muet qu'on cherche à éliminer. */
const disarmed = computed(() => props.summary?.country_disarmed === true)

const singleFaible = computed(
  () => props.summary != null && props.summary.n_open_single > 0
    && (props.summary.best_spread_single ?? 0) < 0.05,
)
const lotFaible = computed(
  () => props.summary != null && props.summary.n_open_lot > 0
    && (props.summary.best_spread_lot ?? 0) < 0.05,
)
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
        type="button" class="chip"
        :class="{ 'chip--on': mode === 'single', 'chip--faible': singleFaible }"
        :disabled="nSingle === 0"
        :title="margeTitle(summary?.best_spread_single, nSingle)"
        @click="emit('mode', 'single')"
      >{{ nSingle ?? '…' }} à l'unité{{ margeLabel(summary?.best_spread_single) }}</button>
      <button
        type="button" class="chip"
        :class="{ 'chip--on': mode === 'lot', 'chip--faible': lotFaible }"
        :disabled="nLot === 0"
        :title="margeTitle(summary?.best_spread_lot, nLot)"
        @click="emit('mode', 'lot')"
      >{{ nLot ?? '…' }} en lots{{ margeLabel(summary?.best_spread_lot) }}</button>
    </span>

    <span class="ranks" title="Jusqu'où descendre dans les hypothèses du modèle. Top 1 = sa première réponse. Top 3 / Top 5 élargissent le filet quand la classe est affamée, au prix de plus de faux à écarter à l'œil.">
      <button
        v-for="r in RANKS" :key="r" type="button"
        class="chip chip--rank" :class="{ 'chip--on': rank === r }"
        @click="emit('rank', r)"
      >Top {{ r }}</button>
    </span>

    <!-- Le filtre pays. Actif par défaut, et il DIT ce qu'il masque : mesuré
         le 2026-08-20, il coupe ~91 % des faux positifs mais écarte aussi ~5 %
         de vrais (des coffrets multi-pays). Un filtre muet mentirait par
         omission ; celui-ci porte son propre compte. -->
    <button
      type="button"
      class="chip chip--pays"
      :class="{ 'chip--on': countryOnly && !disarmed, 'chip--disarmed': disarmed }"
      :title="disarmed
        ? `Filtre pays DÉSARMÉ (O4c) : il aurait vidé entièrement cette file — aucun candidat ne vient d'une annonce ${summary?.country}. Le back sert donc le pool brut, et le dit plutôt que de rendre zéro. Rappel : listing_country n'est pas le pays de l'annonce mais celui que la recherche VISAIT — là où on n'a jamais scrapé, il ne reste rien.`
        : countryOnly
        ? `Seules les annonces du pays de la classe sont servies. Mesuré : la précision du top-1 passe de 91,3 % à 99,1 % sur une pièce courante, en gardant 95 % des vrais positifs. Les ${summary?.n_other_country ?? 0} crops masqués sont surtout des coffrets multi-pays — clique pour les ramener.`
        : 'Filtre levé : les annonces de tous les pays sont servies. Sur une classe courante, environ un crop sur dix est alors un faux positif d\'un autre pays.'"
      @click="emit('country-only', !countryOnly)"
    >
      <template v-if="disarmed">⚠ pays {{ summary?.country ?? '—' }} — désarmé</template>
      <template v-else>{{ countryOnly ? `pays ${summary?.country ?? '—'}` : 'tous pays' }}<span
        v-if="countryOnly && (summary?.n_other_country ?? 0) > 0"
      > · {{ summary?.n_other_country }} masqués</span></template>
    </button>

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
/* Aucun crop au-dessus du seuil du verdict : la file existe, elle ne vaut
   probablement rien. On le montre, on ne désactive pas — c'est un avis. */
.chip--faible { border-style: dashed; color: var(--warning); border-color: var(--warning); }
.chip--disarmed {
  border-color: var(--warning);
  color: var(--warning);
  background: rgba(216, 138, 45, 0.1);
}
.chip--pays { border-style: dashed; }
.chip--orphan {
  display: inline-flex; align-items: center; gap: 5px;
  border-color: var(--warning); color: var(--warning);
}
.chip:disabled { opacity: 0.4; cursor: not-allowed; }
.chip:focus-visible { outline: 2px solid var(--gold); outline-offset: 1px; }
</style>
