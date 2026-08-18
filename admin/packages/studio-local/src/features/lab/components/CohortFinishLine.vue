<script setup lang="ts">
// La ligne d'arrivée — une piste, un trait par classe, placé selon ses photos
// validées. Le trait doré = le plancher, qui vient du back (jamais d'ici).
// Répond d'un coup d'œil à « où en est la cohorte » sans lire les 129 lignes du
// tiroir eBay. Lecture seule.
//
// L'ÉCHELLE N'EST PAS UN SEUIL. Le bout de la piste était fixé à 30, un chiffre
// que personne n'avait éprouvé. Il est maintenant tiré des données : la classe
// la plus fournie de la cohorte. La piste se relit donc « qui est loin derrière
// qui », et le seul repère normatif dessus est le plancher.

import { computed } from 'vue'
import type { CohortClass } from '@/features/lab/composables/useCohortFloor'

const props = defineProps<{ classes: CohortClass[]; floor: number }>()

/** Bout de piste : la classe la plus fournie, jamais moins que le plancher +
 *  un tiers (sinon, cohorte toute neuve, le plancher serait collé au bord). */
const scale = computed(() => {
  const max = props.classes.reduce((m, c) => Math.max(m, c.have), 0)
  return Math.max(max, Math.ceil(props.floor * 1.33), 1)
})

// Position : la classe la plus fournie touche le bout de la piste, les autres
// se placent à sa mesure.
function left(c: CohortClass): string {
  return `${Math.min(c.have / scale.value, 1) * 100}%`
}
function height(c: CohortClass): string {
  return `${16 + Math.min(c.have / scale.value, 1) * 54}px`
}
function tone(c: CohortClass): string {
  if (c.have >= props.floor) return 'pip--ok'
  return c.status === 'block' ? 'pip--block' : 'pip--warn'
}

const floorPct = computed(() => `${Math.min(props.floor / scale.value, 1) * 100}%`)
</script>

<template>
  <div class="track">
    <div class="track__lane" :style="{ '--floor': floorPct }">
      <div class="track__floor"></div>
      <span class="track__lbl track__lbl--floor">plancher {{ floor }}</span>
      <div
        v-for="c in props.classes"
        :key="c.id"
        class="pip"
        :class="tone(c)"
        :style="{ left: left(c), height: height(c) }"
        :title="`${c.label} — ${c.have} photo(s) validée(s)`"
      ></div>
    </div>
    <div class="track__foot">
      <span>0</span>
      <span>chaque trait = une classe · hauteur = photos validées</span>
      <span>{{ scale }}</span>
    </div>
  </div>
</template>

<style scoped>
.track { padding: 0 2px; }
.track__lane {
  position: relative;
  height: 74px;
  border-bottom: 1px solid var(--ink-200);
  background: linear-gradient(
    to right,
    color-mix(in srgb, var(--warning) 7%, transparent) 0 var(--floor),
    transparent var(--floor)
  );
}
.track__floor {
  position: absolute;
  top: 0;
  bottom: 0;
  left: var(--floor);
  width: 1px;
  background: var(--gold);
}
.track__lbl {
  position: absolute;
  top: -1px;
  white-space: nowrap;
  font-family: var(--font-mono);
  font-size: 8.5px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  padding: 0 5px;
  background: var(--surface);
}
.track__lbl--floor { left: var(--floor); transform: translateX(-50%); color: var(--gold-700); }
.pip {
  position: absolute;
  bottom: 0;
  width: 5px;
  border-radius: 2px 2px 0 0;
  transform: translateX(-50%);
  transition: left 0.5s cubic-bezier(0.2, 0.7, 0.3, 1), height 0.5s ease;
}
.pip--ok { background: var(--success); opacity: 0.75; }
.pip--warn { background: var(--warning); }
.pip--block { background: var(--danger); }
.track__foot {
  display: flex;
  justify-content: space-between;
  font-family: var(--font-mono);
  font-size: 9.5px;
  color: var(--ink-400);
  margin-top: 7px;
}
@media (prefers-reduced-motion: reduce) {
  .pip { transition: none; }
}
</style>
