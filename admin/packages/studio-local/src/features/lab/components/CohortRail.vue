<script setup lang="ts">
// La frise des 5 vues — le ROUTEUR de la page, pas un tableau de bord.
//
// Chaque vue répond à UNE question et produit UN artefact. Le détail affiché
// sous chaque étape est ce qui RESTE à y faire : les vues se vident à mesure
// qu'on avance, et une frise toute verte veut dire qu'il n'y a plus rien à
// faire avant d'entraîner. C'est l'antidote au scroll infini de l'ancienne page.
//
// Elle ne re-raconte PAS les compteurs de la page cohorte (§Flow) : celle-là
// compte par PIÈCE (129 lignes pour la giga-40), celle-ci par CLASSE (40) — le
// grain auquel l'entraînement raisonne.
//
// Cf. docs/work-in-progress/refacto-page-cohorte/FRONT.md

import { computed } from 'vue'
import type { CohortClass } from '@/features/lab/composables/useCohortFloor'

export type CohortView = 'classes' | 'matiere' | 'crops' | 'validees' | 'modele'

const props = defineProps<{
  cohortId: string
  view: CohortView
  classes: CohortClass[]
  belowFloor: CohortClass[]
  needSourcing: CohortClass[]
  needCrops: CohortClass[]
  nMissing: number
  ready: boolean
}>()

const emit = defineEmits<{ (e: 'view', value: CohortView): void }>()

type Tone = 'done' | 'todo' | 'warn' | 'blocked'
interface Step {
  n: number
  id: CohortView
  title: string
  /** La question à laquelle la vue répond — affichée, pas seulement documentée. */
  question: string
  /** Ce qui RESTE à faire ici. Une vue vide est une bonne nouvelle. */
  detail: string
  tone: Tone
  hint: string
}

const nCoins = computed(() =>
  props.classes.reduce((a, c) => a + c.members.length, 0),
)
const nNeverCropped = computed(() =>
  props.needCrops.reduce((a, c) => a + c.neverCropped, 0),
)
const nOpen = computed(() =>
  props.belowFloor.reduce((a, c) => a + c.openSingle + c.openLot, 0),
)

const steps = computed<Step[]>(() => [
  {
    n: 1,
    id: 'classes',
    title: 'Classes',
    question: "qu'est-ce qu'on veut reconnaître ?",
    detail: `${props.classes.length} classes · ${nCoins.value} pièces`,
    tone: 'done',
    hint: `${props.classes.length} classe(s) pour ${nCoins.value} pièce(s) — plusieurs `
      + `pièces qui partagent leur face nationale ne font qu'une classe`,
  },
  {
    n: 2,
    id: 'matiere',
    title: 'Matière',
    question: 'a-t-on des images ?',
    detail: props.needSourcing.length > 0
      ? `${props.needSourcing.length} à sourcer`
      : 'le tri suffit',
    tone: props.needSourcing.length > 0 ? 'warn' : 'done',
    hint: props.needSourcing.length > 0
      ? `${props.needSourcing.length} classe(s) que le tri seul n'amènera pas au plancher`
      : 'Aucune classe à sourcer : le stock déjà scrapé suffit partout',
  },
  {
    n: 3,
    id: 'crops',
    title: 'Crops',
    question: 'a-t-on des découpes ?',
    detail: nNeverCropped.value > 0
      ? `${nNeverCropped.value.toLocaleString('fr-FR')} images à découper`
      : 'rien en attente',
    tone: nNeverCropped.value > 0 ? 'todo' : 'done',
    hint: nNeverCropped.value > 0
      ? `${nNeverCropped.value.toLocaleString('fr-FR')} image(s) téléchargée(s) dont aucun `
        + `crop n'est sorti, sur ${props.needCrops.length} classe(s) — le gisement le moins cher`
      : "Toutes les images téléchargées ont donné au moins un crop",
  },
  {
    n: 4,
    id: 'validees',
    title: 'Validées',
    question: 'lesquelles sont sûres ?',
    detail: props.belowFloor.length > 0
      ? `${props.nMissing} photos à valider`
      : 'plancher atteint',
    tone: props.belowFloor.length > 0 ? 'warn' : 'done',
    hint: props.belowFloor.length > 0
      ? `${props.belowFloor.length} classe(s) sous le plancher · ${props.nMissing} photo(s) `
        + `à valider · ${nOpen.value.toLocaleString('fr-FR')} crop(s) en attente de verdict`
      : 'Toutes les classes ont franchi le plancher',
  },
  {
    n: 5,
    id: 'modele',
    title: 'Modèle',
    question: 'est-ce que ça marche ?',
    detail: props.ready ? 'prêt à entraîner' : 'bloqué',
    tone: props.ready ? 'todo' : 'blocked',
    hint: props.ready
      ? "Le contrôle avant entraînement passe — l'itération peut être créée"
      : `Bloqué : ${props.belowFloor.length} classe(s) n'ont pas franchi le plancher`,
  },
])

const ICON: Record<Tone, string> = { done: '✓', todo: '◐', warn: '⚠', blocked: '—' }
</script>

<template>
  <nav class="rail" aria-label="Les 5 vues de la cohorte">
    <ol class="rail__steps">
      <li v-for="s in steps" :key="s.n">
        <button
          type="button"
          class="step"
          :class="[`step--${s.tone}`, { 'step--current': s.id === props.view }]"
          :title="s.hint"
          :aria-current="s.id === props.view ? 'page' : undefined"
          @click="emit('view', s.id)"
        >
          <span class="step__n">{{ s.n }}</span>
          <span class="step__t">{{ s.title }}</span>
          <span class="step__q">{{ s.question }}</span>
          <span class="step__d"><i>{{ ICON[s.tone] }}</i> {{ s.detail }}</span>
        </button>
      </li>
    </ol>
    <p class="rail__legend">
      Chaque vue ne montre que ce qui lui reste à faire — une vue vide veut dire
      que l'étape est finie, pas qu'elle est cassée.
      <RouterLink class="rail__away" :to="`/lab/cohorts/${cohortId}`">
        page cohorte complète ↗
      </RouterLink>
    </p>
  </nav>
</template>

<style scoped>
.rail {
  margin: 14px 0 26px;
  border: 1px solid var(--surface-3);
  border-radius: 10px;
  background: color-mix(in srgb, var(--surface-1) 45%, var(--surface));
  padding: 13px 15px 11px;
}
.rail__steps {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  list-style: none;
  margin: 0;
  padding: 0;
}
.rail__steps > li { min-width: 0; display: flex; }
.step {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 11px;
  border-top: 1px solid var(--surface-3);
  border-bottom: 1px solid var(--surface-3);
  border-right: 1px dashed var(--surface-2);
  border-left: 0;
  background: var(--surface);
  font: inherit;
  color: inherit;
  text-align: left;
  text-decoration: none;
  min-width: 0;
  cursor: pointer;
  transition: background 0.16s ease;
}
.rail__steps > li:first-child .step {
  border-left: 1px solid var(--surface-3);
  border-radius: 6px 0 0 6px;
}
.rail__steps > li:last-child .step {
  border-right: 1px solid var(--surface-3);
  border-radius: 0 6px 6px 0;
}
.step:hover { background: var(--surface-1); }
.step:focus-visible { outline: 2px solid var(--gold); outline-offset: -2px; }
.step--current { background: var(--surface); box-shadow: inset 0 -3px 0 var(--gold); }
.step--current .step__t { color: var(--gold-700); }

.step__n { font-family: var(--font-mono); font-size: 8.5px; color: var(--ink-300); }
.step__t { font-size: 13px; font-weight: 700; line-height: 1.15; }
.step__q {
  font-size: 10.5px;
  font-style: italic;
  color: var(--ink-400);
  line-height: 1.25;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.step__d {
  font-family: var(--font-mono);
  font-size: 9.5px;
  color: var(--ink-500);
  margin-top: 5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.step__d i { font-style: normal; }
.step--done .step__d i { color: var(--success); }
.step--todo .step__d i { color: var(--indigo-700); }
.step--warn .step__d i { color: var(--warning); }
.step--blocked .step__d i { color: var(--danger); }

.rail__legend {
  margin: 9px 0 0;
  font-size: 10.5px;
  color: var(--ink-400);
  display: flex;
  justify-content: space-between;
  gap: 16px;
}
.rail__away { color: var(--ink-400); text-decoration: none; white-space: nowrap; }
.rail__away:hover { color: var(--ink); text-decoration: underline; }

@media (max-width: 820px) {
  .rail__steps { grid-template-columns: repeat(2, 1fr); }
  .rail__steps > li .step { border: 1px solid var(--surface-3); border-radius: 6px; }
}
@media (prefers-reduced-motion: reduce) {
  .step { transition: none; }
}
</style>
