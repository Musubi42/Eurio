<script setup lang="ts">
// VUE 3 — Crops. « A-t-on des découpes exploitables ? »
//
// Ne liste que les classes ayant des images téléchargées dont AUCUN crop n'est
// sorti. C'est le gisement le moins cher de la cohorte : 4 486 images sur la
// giga-40, dont la passe de secours bimétal n'a été essayée que sur 11 pièces.
//
// LE PIÈGE QUE CET ÉCRAN EXISTE POUR NE PAS REJOUER : sur les bimétal, la
// détection accroche le motif central, le crop sort trop serré, le filtre le
// jette, et le job conclut « épuisé » sur un stock intact. La passe de secours
// (EURIO_CENSUS_RECOVER) corrige ça et le bouton la pose maintenant toujours —
// mesuré le 2026-08-18 à seuil identique : fr-2010-degaulle 0 → 144 crops sur
// 193 photos, cy-2008 0 → 46/60, de-2009-saarland 0 → 46/60. Un « épuisé »
// affiché ici doit donc vouloir dire épuisé.
//
// Cf. docs/work-in-progress/refacto-page-cohorte/DONNEES.md §3

import { computed, ref } from 'vue'
import {
  useCohortJobsQuery,
  useRecropZeroCoinMutation,
} from '@/features/lab/composables/useLabQueries'
import type { CohortClass } from '@/features/lab/composables/useCohortFloor'
import type { CohortJob, RescuedToSister } from '@/features/lab/types'

const props = defineProps<{
  cohortId: string
  /** Classes ayant au moins une image jamais découpée, les plus fournies d'abord. */
  classes: CohortClass[]
  /** Crops partis sur des pièces sœurs HORS cohorte — affichés, jamais bougés. */
  sisters: RescuedToSister[]
}>()

const jobsQuery = useCohortJobsQuery(() => props.cohortId)
const recrop = useRecropZeroCoinMutation(() => props.cohortId)

/** Dernier job de découpe par pièce (les jobs arrivent du plus récent au plus
 *  ancien côté back ; on garde le premier vu). */
const lastJob = computed(() => {
  const m = new Map<string, CohortJob>()
  for (const j of jobsQuery.data.value ?? []) {
    if (j.kind !== 'recrop_zero') continue
    const id = j.eurio_id ?? j.target_eurio_id
    if (!id || m.has(id)) continue
    m.set(id, j)
  }
  return m
})

const pending = ref(new Set<string>())

async function launch(eurioId: string) {
  const next = new Set(pending.value)
  next.add(eurioId)
  pending.value = next
  try {
    await recrop.mutateAsync(eurioId)
    await jobsQuery.refetch()
  } finally {
    const after = new Set(pending.value)
    after.delete(eurioId)
    pending.value = after
  }
}

function isRunning(eurioId: string): boolean {
  return pending.value.has(eurioId) || lastJob.value.get(eurioId)?.status === 'running'
}

/** Le résultat d'un job, dit en artefact — pas en étage technique. */
function outcome(j: CohortJob | undefined): string | null {
  if (!j) return null
  if (j.status === 'running') {
    const total = j.n_total ?? 0
    return total > 0 ? `découpe en cours — ${j.n_done}/${total}` : 'découpe en cours'
  }
  if (j.status === 'failed') return j.error ?? 'échec de la découpe'
  // `skipped` = le job n'a PAS tourné. Sans cette branche, il tombait sur
  // « 0 crop récupéré — stock réellement épuisé » : mot pour mot le mensonge
  // que l'en-tête de ce fichier existe pour ne pas rejouer.
  if (j.status === 'skipped') {
    return j.note ?? 'découpe non lancée (rien à découper, ou déjà en cours)'
  }
  if (j.n_produced > 0) {
    return `+${j.n_produced} crop(s) récupéré(s) sur ${j.n_done} image(s) rouverte(s)`
  }
  return j.note ?? '0 crop récupéré — stock réellement épuisé à ce seuil'
}

const nTotal = computed(() => props.classes.reduce((a, c) => a + c.neverCropped, 0))
const nSisters = computed(() => props.sisters.reduce((a, s) => a + s.n, 0))
const sistersOpen = ref(false)
/** Les pièces sœurs, regroupées : 37 lignes brutes se lisent mal. */
const sistersByCoin = computed(() => {
  const m = new Map<string, number>()
  for (const s of props.sisters) m.set(s.sister_eurio_id, (m.get(s.sister_eurio_id) ?? 0) + s.n)
  return [...m.entries()].map(([id, n]) => ({ id, n })).sort((a, b) => b.n - a.n)
})
</script>

<template>
  <section>
    <header class="head">
      <h2 class="h">Les images qui n'ont donné aucune découpe</h2>
      <p class="lede">
        <template v-if="nTotal > 0">
          <b>{{ nTotal.toLocaleString('fr-FR') }} images</b> téléchargées sur
          {{ classes.length }} classe(s) n'ont jamais produit un seul crop. Relancer
          la découpe ne coûte ni quota eBay ni tri : c'est du stock déjà payé.
        </template>
        <template v-else>
          Toutes les images téléchargées ont donné au moins un crop. Rien à faire ici.
        </template>
      </p>
      <p class="note">
        La découpe lancée d'ici utilise toujours la <b>passe de secours</b> —
        celle qui rattrape les bimétal sous-croppés. Sans elle, un job pouvait
        annoncer « épuisé » sur un stock intact.
      </p>
    </header>

    <ul v-if="classes.length > 0" class="list">
      <li v-for="c in classes" :key="c.id" class="klass">
        <div class="klass__head">
          <div>
            <div class="klass__name">{{ c.label }}</div>
            <div class="klass__sub">
              {{ c.neverCropped.toLocaleString('fr-FR') }} image(s) jamais découpée(s)
              · {{ c.have }} photo(s) déjà validée(s)
            </div>
          </div>
        </div>

        <div v-for="m in c.zeroByMember" :key="m.eurioId" class="coin">
          <span class="coin__id">{{ m.eurioId }}</span>
          <span class="coin__n">{{ m.n }} image<template v-if="m.n > 1">s</template></span>
          <span class="coin__out" :class="{ 'coin__out--run': isRunning(m.eurioId) }">
            {{ outcome(lastJob.get(m.eurioId)) ?? '—' }}
          </span>
          <button
            type="button"
            class="btn"
            :disabled="isRunning(m.eurioId)"
            @click="launch(m.eurioId)"
          >
            {{ isRunning(m.eurioId) ? 'en cours…' : (lastJob.get(m.eurioId) ? 'relancer' : 'découper') }}
          </button>
        </div>
      </li>
    </ul>

    <!-- D4 : on AFFICHE la fuite, on ne la répare pas. Ces crops ne sont pas
         perdus — ils sont ailleurs, et personne ne le disait. -->
    <div v-if="nSisters > 0" class="leak">
      <button type="button" class="leak__head" @click="sistersOpen = !sistersOpen">
        <span class="leak__mark">⚠</span>
        <span>
          <b>{{ nSisters }} crops</b> sont partis sur
          <b>{{ sistersByCoin.length }} pièces hors cohorte</b>
        </span>
        <span class="leak__chev">{{ sistersOpen ? '▴' : '▾' }}</span>
      </button>
      <p class="leak__say">
        La découverte eBay se fait par pays entier : viser une pièce ramène tout
        le 2 € du pays, et une partie des crops se range sous des pièces sœurs
        que cette cohorte ne contient pas. Ces crops <b>restent en base</b> et
        n'entraîneront rien tant que ces pièces ne seront pas dans une cohorte.
        On ne les récupère pas : une version colorée n'est pas une standard, et
        la réattribuer polluerait la classe qu'on cherche à mesurer.
      </p>
      <ul v-if="sistersOpen" class="leak__list">
        <li v-for="s in sistersByCoin" :key="s.id">
          <RouterLink class="leak__link" :to="`/coins/${s.id}`">{{ s.id }}</RouterLink>
          <span class="leak__n">{{ s.n }} crop<template v-if="s.n > 1">s</template></span>
        </li>
      </ul>
    </div>
  </section>
</template>

<style scoped>
.head { margin-bottom: 18px; }
.h {
  font-family: var(--font-display);
  font-size: 19px;
  font-style: italic;
  font-weight: 600;
  margin: 0 0 6px;
}
.lede { margin: 0 0 8px; font-size: 13.5px; color: var(--ink-700); max-width: 70ch; }
.note { margin: 0; font-size: 12px; color: var(--ink-500); max-width: 70ch; }

.list { list-style: none; margin: 0; padding: 0; }
.klass {
  border: 1px solid var(--surface-3);
  border-radius: 9px;
  padding: 12px 14px;
  margin-bottom: 10px;
  background: var(--surface);
}
.klass__head { display: flex; justify-content: space-between; gap: 16px; margin-bottom: 8px; }
.klass__name { font-size: 13.5px; font-weight: 600; }
.klass__sub { font-family: var(--font-mono); font-size: 10px; color: var(--ink-400); margin-top: 2px; }

.coin {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 92px minmax(0, 1.4fr) auto;
  gap: 12px;
  align-items: center;
  padding: 6px 0;
  border-top: 1px solid var(--surface-2);
}
.coin__id {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--ink-700);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.coin__n { font-family: var(--font-mono); font-size: 10.5px; color: var(--ink-500); }
.coin__out { font-size: 11.5px; color: var(--ink-500); }
.coin__out--run { color: var(--indigo-700); }

.btn {
  font: inherit;
  font-size: 12px;
  padding: 4px 12px;
  border: 1px solid var(--ink-200);
  border-radius: 6px;
  background: var(--surface);
  cursor: pointer;
  white-space: nowrap;
}
.btn:hover { background: var(--surface-1); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }

.leak {
  margin-top: 24px;
  border: 1px solid color-mix(in srgb, var(--warning) 34%, transparent);
  background: color-mix(in srgb, var(--warning) 7%, transparent);
  border-radius: 9px;
  padding: 12px 14px;
}
.leak__head {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  background: none;
  border: 0;
  padding: 0;
  font: inherit;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}
.leak__mark { color: var(--warning); }
.leak__chev { margin-left: auto; color: var(--ink-400); }
.leak__say { margin: 8px 0 0; font-size: 12.5px; color: var(--ink-700); max-width: 78ch; }
.leak__list {
  list-style: none;
  margin: 12px 0 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px 9px;
}
.leak__list li {
  font-family: var(--font-mono);
  font-size: 10.5px;
  background: var(--surface);
  border: 1px solid var(--surface-3);
  border-radius: 5px;
  padding: 2px 7px;
}
.leak__link { color: var(--ink-700); text-decoration: none; }
.leak__link:hover { color: var(--indigo-700); text-decoration: underline; }
.leak__n { color: var(--ink-400); margin-left: 7px; }

@media (max-width: 820px) {
  .coin { grid-template-columns: 1fr auto; }
  .coin__out { grid-column: 1 / -1; }
}
</style>
