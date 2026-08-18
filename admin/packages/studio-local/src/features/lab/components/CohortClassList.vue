<script setup lang="ts">
// VUE 1 — Classes. « Qu'est-ce qu'on veut reconnaître ? »
//
// Le modèle n'apprend pas une PIÈCE, il apprend un DESSIN. Plusieurs pièces qui
// partagent leur face nationale forment une seule classe, et leurs photos
// s'additionnent : sur la giga-40, 129 pièces font 40 classes, et le drapeau
// européen 2015 en regroupe 21 à lui seul.
//
// C'est l'information la plus rentable de la page, et celle qu'aucun écran ne
// donnait : la vue sourcing collapse les millésimes d'une ère sur une ligne, si
// bien que 7 pièces de la giga-40 n'y apparaissent nulle part. Elles sont bien
// rattachées à leur classe et seront entraînées — mais on croyait les avoir
// perdues. Ici, chaque pièce est visible sous sa classe, dépliable.
//
// Cf. docs/work-in-progress/refacto-page-cohorte/DONNEES.md §1

import { computed, ref } from 'vue'
import type { CohortClass } from '@/features/lab/composables/useCohortFloor'

const props = defineProps<{
  cohortId: string
  classes: CohortClass[]
  floor: number
  /** eurio_ids de la cohorte qu'aucune classe n'a pu résoudre (réf morte). */
  unresolved: string[]
}>()

const openIds = ref(new Set<string>())
function toggle(id: string) {
  const next = new Set(openIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  openIds.value = next
}

type Sort = 'regroupement' | 'photos' | 'alpha'
const sort = ref<Sort>('regroupement')

const sorted = computed(() => {
  const rows = [...props.classes]
  if (sort.value === 'photos') return rows.sort((a, b) => a.have - b.have)
  if (sort.value === 'alpha') return rows.sort((a, b) => a.label.localeCompare(b.label, 'fr'))
  // Par défaut : les gros regroupements d'abord — c'est ce qui surprend, donc
  // ce qu'il faut voir en premier.
  return rows.sort((a, b) => b.members.length - a.members.length || a.label.localeCompare(b.label, 'fr'))
})

const nCoins = computed(() => props.classes.reduce((a, c) => a + c.members.length, 0))
const grouped = computed(() => props.classes.filter(c => c.members.length > 1))
const nGrouped = computed(() => grouped.value.reduce((a, c) => a + c.members.length, 0))

/** Sans avers Numista ni réf officielle : rien pour ancrer la classe. */
const noReference = computed(() => props.classes.filter(c => c.nNumista === 0 && c.nRef === 0))

/** Les pièces que la vue sourcing ne montre nulle part (millésimes collapsés
 *  sur la ligne de leur ère). Elles sont entraînées ; on croyait les avoir
 *  perdues. Les nommer une fois suffit à clore la question. */
const hidden = computed(() => props.classes.flatMap(c => c.hiddenMembers))
</script>

<template>
  <section>
    <header class="head">
      <div>
        <h2 class="h">La cohorte, telle que le modèle la voit</h2>
        <p class="lede">
          <b>{{ nCoins }} pièces</b> forment <b>{{ classes.length }} classes</b>.
          <template v-if="grouped.length > 0">
            {{ nGrouped }} de ces pièces partagent leur face nationale avec une
            autre : trier une seule de leurs photos fait monter toute la classe.
          </template>
          <template v-else>
            Aucune pièce n'en rejoint une autre : ici une classe = une pièce.
          </template>
        </p>
      </div>
      <div class="sortbox">
        <label class="eyebrow" for="cl-sort">trier par</label>
        <select id="cl-sort" v-model="sort" class="sel">
          <option value="regroupement">regroupement</option>
          <option value="photos">photos validées</option>
          <option value="alpha">nom</option>
        </select>
      </div>
    </header>

    <!-- Ce qui bloque l'entraînement AVANT tout tri : une pièce qui n'existe
         plus au catalogue, une classe sans aucune face de référence. -->
    <p v-if="hidden.length > 0" class="alert alert--info">
      <b>{{ hidden.length }} pièce(s) n'apparaissent nulle part dans la vue sourcing</b> —
      celle-ci regroupe les millésimes d'une même ère sur une seule ligne. Elles
      sont bien rattachées à leur classe et seront entraînées ; on les retrouve
      en dépliant les classes ci-dessous ({{ hidden.join(', ') }}).
    </p>
    <p v-if="props.unresolved.length > 0" class="alert alert--bad">
      <b>{{ props.unresolved.length }} pièce(s) de la cohorte n'existent pas au catalogue</b>
      ({{ props.unresolved.join(', ') }}). Elles ne seront jamais entraînées : le
      contrôle avant entraînement les refuse. Retire-les ou corrige leur identifiant.
    </p>
    <p v-if="noReference.length > 0" class="alert">
      <b>{{ noReference.length }} classe(s) sans face de référence</b> (ni avers
      Numista, ni réf officielle BCE/JO). Elles ne s'appuient que sur les crops
      eBay validés — la moindre erreur de tri s'y voit tout de suite.
    </p>

    <ul class="list">
      <li v-for="c in sorted" :key="c.id" class="row" :class="{ 'row--open': openIds.has(c.id) }">
        <button
          type="button"
          class="row__main"
          :aria-expanded="openIds.has(c.id)"
          @click="toggle(c.id)"
        >
          <span class="row__chev">{{ openIds.has(c.id) ? '▾' : '▸' }}</span>

          <span class="row__id">
            <span class="row__name">{{ c.label }}</span>
            <span class="row__slug">{{ c.id }}</span>
          </span>

          <span class="row__tags">
            <span v-if="c.kind === 'design_group_id'" class="tag tag--era">ère</span>
            <span v-else class="tag">pièce</span>
            <span class="tag tag--n">{{ c.members.length }}
              pièce<template v-if="c.members.length > 1">s</template>
            </span>
          </span>

          <span class="row__have" :class="c.have >= floor ? 'is-ok' : 'is-low'">
            {{ c.have }} <span class="row__den">/ {{ floor }}</span>
          </span>

          <span class="row__src">
            <span :title="`${c.nNumista} avers Numista, ${c.nRef} réf officielle(s), ${c.have} crops eBay validés`">
              seed {{ c.seed }}
            </span>
            <span class="row__aug" :title="`Le bake gonflera cette classe ×${c.augFactor} pour atteindre la cible`">
              ×{{ c.augFactor }}
            </span>
          </span>
        </button>

        <div v-if="openIds.has(c.id)" class="row__body">
          <p class="row__why">
            <template v-if="c.members.length > 1">
              Ces {{ c.members.length }} pièces ne font qu'une classe : leurs photos
              s'additionnent, et une photo de n'importe laquelle nourrit l'ensemble.
            </template>
            <template v-else>
              Cette classe n'a qu'une pièce — ses photos ne viennent que d'elle.
            </template>
          </p>
          <ul class="members">
            <li
              v-for="m in c.members"
              :key="m"
              :class="{ 'members__dead': c.missingMembers.includes(m) }"
            >
              <RouterLink class="members__link" :to="`/coins/${m}`">{{ m }}</RouterLink>
              <span v-if="c.missingMembers.includes(m)" class="members__flag">
                absente du catalogue
              </span>
              <span
                v-else-if="c.hiddenMembers.includes(m)"
                class="members__hidden"
                title="Collapsée sur la ligne de son ère dans la vue sourcing — bien entraînée"
              >
                invisible au sourcing
              </span>
            </li>
          </ul>
          <p v-if="c.reason" class="row__reason">{{ c.reason }}</p>
        </div>
      </li>
    </ul>

    <p class="foot">
      Ajouter ou retirer une pièce se fait depuis
      <RouterLink :to="`/lab/cohorts/${cohortId}?tiroir=c1`">la page cohorte</RouterLink> —
      et seulement tant que la cohorte n'est pas gelée (la première itération la fige).
    </p>
  </section>
</template>

<style scoped>
.head {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 24px;
  margin-bottom: 16px;
}
.h {
  font-family: var(--font-display);
  font-size: 19px;
  font-style: italic;
  font-weight: 600;
  margin: 0 0 6px;
}
.lede { margin: 0; font-size: 13.5px; color: var(--ink-700); max-width: 68ch; }
.eyebrow {
  font-family: var(--font-mono);
  font-size: 9.5px;
  text-transform: uppercase;
  letter-spacing: var(--tracking-eyebrow);
  color: var(--ink-400);
  margin-right: 6px;
}
.sel {
  font: inherit;
  font-size: 12px;
  padding: 3px 7px;
  border: 1px solid var(--ink-200);
  border-radius: 6px;
  background: var(--surface);
}

.alert {
  margin: 0 0 12px;
  padding: 9px 13px;
  border-radius: 8px;
  font-size: 12.5px;
  background: color-mix(in srgb, var(--warning) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--warning) 34%, transparent);
  color: var(--ink-700);
}
.alert--info {
  background: color-mix(in srgb, var(--indigo-700) 7%, transparent);
  border-color: color-mix(in srgb, var(--indigo-700) 24%, transparent);
}
.alert--bad {
  background: color-mix(in srgb, var(--danger) 9%, transparent);
  border-color: color-mix(in srgb, var(--danger) 32%, transparent);
}

.list { list-style: none; margin: 0; padding: 0; }
.row { border-bottom: 1px solid var(--surface-2); }
.row--open { background: color-mix(in srgb, var(--surface-1) 55%, transparent); }
.row__main {
  width: 100%;
  display: grid;
  grid-template-columns: 16px minmax(0, 1fr) auto 96px 118px;
  align-items: center;
  gap: 14px;
  padding: 10px 6px;
  background: none;
  border: 0;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.row__main:hover { background: var(--surface-1); }
.row__main:focus-visible { outline: 2px solid var(--gold); outline-offset: -2px; }
.row__chev { color: var(--ink-300); font-size: 11px; }
.row__id { min-width: 0; }
.row__name { display: block; font-size: 13.5px; font-weight: 600; }
.row__slug {
  display: block;
  font-family: var(--font-mono);
  font-size: 9.5px;
  color: var(--ink-400);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.row__tags { display: flex; gap: 5px; }
.row__have { font-family: var(--font-mono); font-size: 13px; text-align: right; }
.row__have.is-ok { color: var(--success); }
.row__have.is-low { color: var(--warning); }
.row__den { color: var(--ink-300); font-size: 10.5px; }
.row__src {
  display: flex;
  justify-content: flex-end;
  gap: 9px;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--ink-400);
  cursor: help;
}
.row__aug { color: var(--indigo-700); }

.row__body { padding: 2px 6px 14px 46px; }
.row__why { margin: 0 0 8px; font-size: 12.5px; color: var(--ink-500); max-width: 70ch; }
.members {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 5px 8px;
}
.members li {
  font-family: var(--font-mono);
  font-size: 10.5px;
  background: var(--surface);
  border: 1px solid var(--surface-3);
  border-radius: 5px;
  padding: 2px 7px;
}
.members__link { color: var(--ink-700); text-decoration: none; }
.members__link:hover { color: var(--indigo-700); text-decoration: underline; }
.members__dead { border-color: color-mix(in srgb, var(--danger) 45%, transparent); }
.members__flag { color: var(--danger); margin-left: 6px; }
.members__hidden { color: var(--indigo-700); margin-left: 6px; cursor: help; }
.row__reason { margin: 9px 0 0; font-size: 12px; color: var(--warning); }

.tag {
  font-family: var(--font-mono);
  font-size: 8.5px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--surface-2);
  color: var(--ink-500);
  white-space: nowrap;
}
.tag--era { background: color-mix(in srgb, var(--indigo-700) 12%, transparent); color: var(--indigo-700); }
.tag--n { background: color-mix(in srgb, var(--gold) 16%, transparent); color: var(--gold-700); }

.foot { margin: 16px 0 0; font-size: 12px; color: var(--ink-500); }
.foot a { color: var(--indigo-700); }

@media (max-width: 900px) {
  .row__main { grid-template-columns: 16px minmax(0, 1fr) auto; }
  .row__have, .row__src { grid-column: 2 / -1; justify-content: flex-start; text-align: left; }
}
</style>
