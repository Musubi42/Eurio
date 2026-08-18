<script setup lang="ts">
// Bandeau cohorte — posé AU-DESSUS de la barre d'actions de la review, jamais
// dedans : la page sœur ne modifie aucun fichier de /review. Il suit la classe
// en main pendant qu'on tranche, et survit à la bascule single ↔ lot puisqu'il
// appartient à la page, pas à la vue montée en dessous.
//
// Règle : au plancher on est AUTORISÉ à partir, rien ne pousse. Il n'y a plus
// de « plafond » à 30 qui faisait basculer tout seul — ce chiffre n'était fondé
// sur rien. Au-dessus du plancher, ce qu'on montre est le FACTEUR
// D'AUGMENTATION (×10 = neuf images sur dix seront des variations de la même
// photo) : une grandeur que le bake calcule vraiment.

import { computed } from 'vue'
import type { CohortClass } from '@/features/lab/composables/useCohortFloor'

const props = defineProps<{
  klass: CohortClass
  /** Plancher résolu au canonique — le front n'en définit aucun. */
  floor: number
  mode: 'single' | 'lot'
  /** Secondes écoulées depuis le dernier changement observé du compteur. */
  sinceChange: number
  /** D'où vient le compteur : direct, encore en vol, ou repli local. */
  source: 'live' | 'loading' | 'fallback'
  /** Décalage à annoncer en repli sur la copie locale. */
  lagSeconds: number
}>()

const emit = defineEmits<{
  (e: 'next'): void
  (e: 'mode', value: 'single' | 'lot'): void
  (e: 'close'): void
}>()

const cleared = computed(() => props.klass.have >= props.floor)
const pct = computed(
  () => `${Math.min((props.klass.have / Math.max(props.floor, 1)) * 100, 100)}%`,
)
// En repli sur la copie locale seulement : elle ne se rafraîchit que toutes les
// `lagSeconds`, un tri récent n'est pas perdu, il n'est pas encore arrivé.
const live = computed(() => props.source === 'live' && props.klass.haveIsLive)
const late = computed(() => !live.value && props.sinceChange > props.lagSeconds)
const sourceHint = computed(() => {
  if (props.source === 'loading') return 'Compteur en cours de lecture au serveur…'
  if (props.source === 'live' && !props.klass.haveIsLive) {
    return 'Le serveur répond, mais pas pour CETTE classe : son compteur vient de '
      + `la copie locale, rafraîchie toutes les ${props.lagSeconds} s.`
  }
  if (props.source === 'live') return 'Compteur lu en direct sur le serveur — pas de décalage.'
  return 'Serveur injoignable : compteur lu sur la copie locale, rafraîchie toutes les '
    + `${props.lagSeconds} s. Une validation peut tarder à apparaître.`
})
const sourceLabel = computed(() => {
  if (props.source === 'loading') return 'lecture…'
  if (live.value) return 'direct'
  return late.value ? `copie locale · ${sinceLabel.value}` : 'copie locale'
})
const sinceLabel = computed(() => `${props.sinceChange}s`)
// Une validation qui ne fait pas monter le compteur a une raison nommable —
// À CONDITION qu'on la connaisse. Ces deux compteurs ne viennent que du
// canonique : tant qu'il n'a pas répondu ils sont `null`, et se taire
// reviendrait à affirmer qu'il n'y a rien à signaler.
const stuckWhy = computed(() => {
  const { reverseFlagged, unknownFace } = props.klass
  if (reverseFlagged === null || unknownFace === null) return ''
  const bits: string[] = []
  if (reverseFlagged > 0) bits.push(`${reverseFlagged} en revers`)
  if (unknownFace > 0) bits.push(`${unknownFace} face non tranchée`)
  return bits.length ? `${bits.join(' · ')} — validées mais hors entraînement` : ''
})
/** Vrai quand on ne peut RIEN dire des raisons — à distinguer de « rien à dire ». */
const stuckUnknown = computed(
  () => props.klass.reverseFlagged === null || props.klass.unknownFace === null,
)
// Singles épuisés mais des lots restent : on PROPOSE la bascule, on ne l'impose
// pas — la vue lot change les touches sous les doigts (J/K, S requalifie).
const offerLot = computed(
  () => props.mode === 'single' && props.klass.openSingle === 0 && props.klass.openLot > 0,
)
</script>

<template>
  <div class="strip" :class="{ 'strip--done': cleared }">
    <span class="strip__lbl">cohorte</span>

    <div class="strip__id">
      <span class="strip__cls">{{ klass.label }}</span>
      <span class="strip__goal">
        {{ cleared
          ? `plancher franchi · augmentation ×${klass.augFactor}`
          : `validées · plancher ${floor}` }}
      </span>
    </div>

    <div class="bar">
      <div class="bar__fill" :class="{ 'bar__fill--done': cleared }" :style="{ width: pct }"></div>
    </div>

    <span class="strip__num">
      {{ klass.have }} <span class="strip__den">/ {{ floor }}</span>
    </span>

    <span class="strip__stock">
      <button
        type="button"
        class="chip"
        :class="{ 'chip--on': mode === 'single' }"
        :disabled="klass.openSingle === 0"
        @click="emit('mode', 'single')"
      >{{ klass.openSingle }} à l'unité</button>
      <button
        type="button"
        class="chip"
        :class="{ 'chip--on': mode === 'lot', 'chip--offer': offerLot }"
        :disabled="klass.openLot === 0"
        @click="emit('mode', 'lot')"
      >{{ klass.openLot }} en lots</button>
      <span class="strip__sync" :class="{ 'strip__sync--wait': late }" :title="sourceHint">
        {{ sourceLabel }}
      </span>
      <span v-if="stuckWhy" class="strip__stuck" :title="stuckWhy">⚠ {{ stuckWhy }}</span>
      <span
        v-else-if="stuckUnknown"
        class="strip__stuck strip__stuck--unknown"
        title="Les crops passés en revers ou à face non tranchée se lisent au serveur, qui n'a pas encore répondu."
      >? raisons inconnues</span>
    </span>

    <button type="button" class="btn btn--ghost" @click="emit('close')">Quitter</button>
    <button
      type="button"
      class="btn btn--next"
      :class="{ 'btn--next-on': cleared }"
      :disabled="!cleared"
      :title="cleared ? 'Classe suivante (P)' : `Encore ${klass.missing} photo(s) avant de pouvoir passer`"
      @click="emit('next')"
    >
      Classe suivante <kbd>P</kbd>
    </button>
  </div>
</template>

<style scoped>
.strip {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  padding: 9px 18px;
  border-top: 1px solid var(--gold);
  background: color-mix(in srgb, var(--gold) 7%, var(--surface));
  transition: background 0.3s ease, border-color 0.3s ease;
}
.strip--done {
  background: color-mix(in srgb, var(--success) 10%, var(--surface));
  border-top-color: var(--success);
}
.strip__lbl {
  font-family: var(--font-mono);
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: var(--tracking-eyebrow);
  color: var(--ink-400);
}
.strip__id { display: flex; flex-direction: column; line-height: 1.2; min-width: 0; }
.strip__cls { font-size: 13px; font-weight: 600; }
.strip__goal {
  font-family: var(--font-mono);
  font-size: 8.5px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--ink-400);
}
.bar {
  position: relative;
  flex: 1;
  min-width: 130px;
  max-width: 260px;
  height: 8px;
  background: var(--surface-2);
  border-radius: 5px;
  overflow: hidden;
}
.bar__fill {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  background: var(--warning);
  border-radius: 5px;
  transition: width 0.45s cubic-bezier(0.2, 0.7, 0.3, 1), background 0.3s;
}
.bar__fill--done { background: var(--success); }
.strip__num {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: 14px;
  font-weight: 500;
  white-space: nowrap;
}
.strip__den { color: var(--ink-400); }
.strip__stock { display: flex; align-items: center; gap: 5px; }
.strip__sync {
  font-family: var(--font-mono);
  font-size: 9px;
  color: var(--ink-400);
  cursor: help;
}
.strip__sync--wait { color: var(--warning); }
.strip__stuck--unknown { color: var(--ink-400) !important; }
.strip__stuck {
  font-family: var(--font-mono);
  font-size: 9px;
  color: var(--warning);
  cursor: help;
}
.chip {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 3px 8px;
  border-radius: 5px;
  border: 1px solid var(--surface-3);
  background: var(--surface);
  color: var(--ink-500);
  cursor: pointer;
}
.chip:disabled { opacity: 0.4; cursor: not-allowed; }
.chip--on { border-color: var(--ink); color: var(--ink); font-weight: 500; }
.chip--offer { border-color: var(--gold); color: var(--gold-700); }
.chip:focus-visible, .btn:focus-visible { outline: 2px solid var(--gold); outline-offset: 1px; }

.btn {
  font-size: 12px;
  font-weight: 500;
  padding: 6px 12px;
  border-radius: 7px;
  border: 1px solid var(--ink-200);
  background: var(--surface);
  color: var(--ink);
  cursor: pointer;
  white-space: nowrap;
}
.btn--ghost { color: var(--ink-500); }
.btn--ghost:hover { color: var(--ink); }
.btn--next { margin-left: auto; opacity: 0.4; cursor: not-allowed; }
.btn--next-on {
  opacity: 1;
  cursor: pointer;
  background: var(--success);
  border-color: var(--success);
  color: var(--surface);
}
kbd {
  font-family: var(--font-mono);
  font-size: 9px;
  padding: 1px 5px;
  border-radius: 4px;
  background: color-mix(in srgb, currentColor 14%, transparent);
  border: 1px solid color-mix(in srgb, currentColor 24%, transparent);
}
@media (prefers-reduced-motion: reduce) {
  .strip, .bar__fill { transition: none; }
}
</style>
