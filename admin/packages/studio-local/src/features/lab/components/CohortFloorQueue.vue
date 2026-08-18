<script setup lang="ts">
// La file — uniquement les classes sous le plancher, la plus rapide à
// débloquer en tête. Chaque ligne dit trois choses : ce qu'il manque, où on en
// est (barre 0 → plancher), et où se trouve le stock (singles vs lots).
//
// La barre va de 0 au PLANCHER, pas à un plafond inventé : toutes ces classes
// sont sous le plancher, c'est la seule distance qui compte ici. Le plancher
// est une prop — il vient du back, jamais de ce fichier.
//
// « Prendre » ouvre la classe dans la review montée par la page sœur. Le mode
// par défaut est Single (plus net à trancher) ; si la classe n'a plus de single
// ouvert, on ouvre directement en Lot — inutile de présenter une file vide.

import type { CohortClass } from '@/features/lab/composables/useCohortFloor'

const props = defineProps<{
  classes: CohortClass[]
  floor: number
  heldId?: string | null
}>()
const emit = defineEmits<{ (e: 'take', klass: CohortClass, mode: 'single' | 'lot'): void }>()

function pct(n: number): string {
  return `${Math.min((n / Math.max(props.floor, 1)) * 100, 100)}%`
}
function defaultMode(c: CohortClass): 'single' | 'lot' {
  return c.openSingle > 0 ? 'single' : 'lot'
}
</script>

<template>
  <div>
    <div v-if="props.classes.length === 0" class="empty">
      Toutes les classes ont franchi le plancher de {{ floor }} photos réelles.
    </div>

    <div v-for="(c, i) in props.classes" :key="c.id" class="row">
      <span class="row__rank">{{ String(i + 1).padStart(2, '0') }}</span>

      <div class="row__id">
        <div class="row__name">
          {{ c.label }}
          <span v-if="c.status === 'block'" class="tag tag--block">bloquée</span>
          <span v-if="c.kind === 'design_group_id'" class="tag tag--era">ère</span>
        </div>
        <div class="row__sub">{{ c.id }}</div>
      </div>

      <div class="row__need">
        <b>{{ c.missing }}</b> à valider
      </div>

      <div class="row__gauge">
        <div class="bar">
          <div class="bar__fill" :style="{ width: pct(c.have) }"></div>
        </div>
        <div
          class="row__stock"
          :title="`${c.openSingle} crop(s) à trancher à l'unité, ${c.openLot} en lots`"
        >
          {{ c.have }} validée<span v-if="c.have > 1">s</span> sur {{ floor }} ·
          {{ c.openSingle + c.openLot }} en attente
        </div>
      </div>

      <div class="row__go">
        <span v-if="c.openSingle + c.openLot === 0" class="mini mini--none" title="Aucun crop à trancher — cette classe a besoin d'être sourcée">
          à sourcer
        </span>
        <button
          v-else
          type="button"
          class="mini"
          :class="c.id === props.heldId ? 'mini--held' : 'mini--go'"
          @click="emit('take', c, defaultMode(c))"
        >
          {{ c.id === props.heldId ? 'ouverte' : 'Prendre' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.empty {
  padding: 22px 4px;
  font-size: 13px;
  color: var(--success);
}
.row {
  display: grid;
  grid-template-columns: 24px 1fr 108px 250px 130px;
  gap: 15px;
  align-items: center;
  padding: 11px 13px;
  border-bottom: 1px solid var(--surface-2);
}
.row:hover { background: var(--surface-1); }
.row__rank { font-family: var(--font-mono); font-size: 10px; color: var(--ink-300); }
.row__id { min-width: 0; }
.row__name {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 13.5px;
  font-weight: 500;
}
.row__sub {
  font-family: var(--font-mono);
  font-size: 9.5px;
  color: var(--ink-400);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.row__need { font-family: var(--font-mono); font-size: 12px; color: var(--ink-500); }
.row__need b { font-size: 15px; font-weight: 500; color: var(--ink); }
.row__stock { font-family: var(--font-mono); font-size: 10px; color: var(--ink-400); margin-top: 5px; white-space: nowrap; cursor: help; }
.row__split { color: var(--ink-300); }
.row__go { display: flex; gap: 6px; justify-content: flex-end; }

.bar {
  position: relative;
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
}
.tag {
  font-family: var(--font-mono);
  font-size: 8.5px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  padding: 2px 6px;
  border-radius: 4px;
}
.tag--block { background: color-mix(in srgb, var(--danger) 15%, transparent); color: var(--danger); }
.tag--era { background: var(--surface-2); color: var(--ink-500); }

.mini {
  font-size: 11.5px;
  font-weight: 500;
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid var(--surface-3);
  background: var(--surface);
  color: var(--ink-700);
  text-decoration: none;
}
.mini:hover { border-color: var(--ink-300); }
.mini--go { background: var(--indigo-700); border-color: var(--indigo-700); color: var(--surface); cursor: pointer; }
.mini--held { background: var(--ink); border-color: var(--ink); color: var(--surface); cursor: pointer; }
.mini--none { color: var(--ink-400); border-style: dashed; cursor: default; }

@media (max-width: 900px) {
  .row { grid-template-columns: 22px 1fr 96px; }
  .row__gauge, .row__go { display: none; }
}
</style>
