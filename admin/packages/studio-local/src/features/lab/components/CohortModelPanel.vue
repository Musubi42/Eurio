<script setup lang="ts">
// VUE 5 — Modèle. « Est-ce que ça marche ? »
//
// Deux moitiés, dans cet ordre : ce qui BLOQUE (le contrôle avant entraînement,
// avec le nom de chaque classe et sa raison), puis ce que le dernier run a
// MESURÉ (R@1 par classe, et surtout les confusions).
//
// Les confusions ne sont pas un détail de rapport : c'est ce qui met à
// l'épreuve la règle de regroupement. « Même face nationale = même classe »
// n'a jamais été éprouvée autrement que par raisonnement. Deux classes qui se
// confondent systématiquement étaient la même ; une classe qui se reconnaît mal
// malgré ses photos a été groupée trop large. C'est un argument pour entraîner
// tôt — le premier run n'est pas seulement un modèle, c'est le test de la règle.
//
// Les captures device se branchent ici et n'empêchent JAMAIS d'entraîner :
// leur absence empêche de mesurer, et l'écran le dit.
//
// Cf. docs/work-in-progress/refacto-page-cohorte/VISION.md

import { computed } from 'vue'
import { useCohortTrainingCropsQuery } from '@/features/lab/composables/useLabQueries'
import type { CohortClass } from '@/features/lab/composables/useCohortFloor'
import type { ResolvedThresholds } from '@/features/lab/types'

const props = defineProps<{
  cohortId: string
  classes: CohortClass[]
  belowFloor: CohortClass[]
  unresolved: string[]
  ready: boolean
  thresholds: ResolvedThresholds
  /**
   * Les seuils que le CONTRÔLE a réellement appliqués (réplique locale), à
   * distinguer de ceux du canonique : pendant les ~2 min de décalage, décrire
   * le verdict avec les seconds ferait citer des nombres que le contrôle n'a
   * jamais vus.
   */
  usedThresholds: ResolvedThresholds | null
}>()

const emit = defineEmits<{ (e: 'goto', view: 'validees' | 'matiere'): void }>()

const cropsQuery = useCohortTrainingCropsQuery(() => props.cohortId)

/** Le contrôle a-t-il tourné sous une autre règle que celle affichée ? */
const stale = computed(() => {
  const used = props.usedThresholds
  if (!used) return false
  return used.min_real !== props.thresholds.min_real
    || used.m_per_class !== props.thresholds.m_per_class
})

/** Ce qui bloque, nommé. Un préflight qui dit « non » sans dire qui est un mur. */
const blockers = computed(() =>
  props.classes
    .filter(c => c.status !== 'ok')
    .sort((a, b) => (a.status === 'block' ? 0 : 1) - (b.status === 'block' ? 0 : 1) || a.have - b.have),
)

/** Mesures du dernier benchmark, les moins bonnes d'abord. Absentes tant qu'aucun
 *  run n'a tourné — ou quand le ML local est éteint (l'overlay est local). */
const measured = computed(() => {
  const rows = (cropsQuery.data.value?.classes ?? []).filter(c => c.r_at_1 !== null)
  return rows.sort((a, b) => (a.r_at_1 ?? 1) - (b.r_at_1 ?? 1))
})
const labelOf = computed(() => {
  const m = new Map(props.classes.map(c => [c.id, c.label]))
  return (id: string) => m.get(id) ?? id
})
function pct(v: number | null): string {
  return v === null ? '—' : `${Math.round(v * 100)} %`
}
const benched = computed(() => cropsQuery.data.value?.benchmark_run_id ?? null)

/** Classes gonflées le plus fort par l'augmentation : neuf images sur dix y
 *  seront des variations de la même photo. Pas un blocage, un risque à voir. */
const mostInflated = computed(() =>
  [...props.classes].sort((a, b) => b.augFactor - a.augFactor).slice(0, 5),
)
</script>

<template>
  <section>
    <!-- ── Ce qui bloque ────────────────────────────────────────────────── -->
    <div class="verdict" :class="ready ? 'verdict--go' : 'verdict--stop'">
      <div class="verdict__mark">{{ ready ? '✓' : '—' }}</div>
      <div>
        <h2 class="h">
          {{ ready ? 'La cohorte peut partir à l’entraînement' : 'L’entraînement est refusé' }}
        </h2>
        <p class="verdict__say">
          <template v-if="ready">
            Les {{ classes.length }} classes passent le contrôle : chacune a au moins
            {{ (usedThresholds ?? thresholds).m_per_class }} sources réelles et
            {{ (usedThresholds ?? thresholds).min_real }} photos validées.
          </template>
          <template v-else>
            {{ blockers.length }} classe(s) ne passent pas le contrôle. Il refuse
            <b>avant</b> de figer la cohorte et de dépenser du GPU — une classe trop
            pauvre s'entraînerait sur des doublons rééchantillonnés, sans signal.
          </template>
        </p>
        <p v-if="stale" class="verdict__stale">
          ⚠ Ce verdict a été calculé avec plancher
          {{ usedThresholds?.min_real }} / refus dur {{ usedThresholds?.m_per_class }},
          alors que le réglage en vigueur est
          {{ thresholds.min_real }} / {{ thresholds.m_per_class }}. Le contrôle lit
          une copie locale rafraîchie toutes les 120 s : il se remettra à jour
          tout seul.
        </p>
        <p class="verdict__seuils">
          refus dur {{ thresholds.m_per_class }} · plancher {{ thresholds.min_real }} ·
          cible {{ thresholds.training_target }} après augmentation —
          <b>ces trois valeurs seront gelées dans l'itération</b>, pour qu'on
          puisse toujours dire sous quelle règle ce modèle a été entraîné.
        </p>
      </div>
      <RouterLink
        v-if="ready"
        class="btn btn--go"
        :to="`/lab/cohorts/${cohortId}/iterations/new`"
      >
        Nouvelle itération
      </RouterLink>
    </div>

    <div v-if="!ready" class="blockers">
      <p v-if="unresolved.length > 0" class="blockers__dead">
        <b>{{ unresolved.length }} pièce(s) absentes du catalogue</b> :
        {{ unresolved.join(', ') }} — à retirer de la cohorte.
      </p>
      <ul class="blockers__list">
        <li v-for="c in blockers" :key="c.id">
          <span class="bk__tag" :class="c.status === 'block' ? 'bk__tag--block' : 'bk__tag--warn'">
            {{ c.status === 'block' ? 'refusée' : 'trop pauvre' }}
          </span>
          <span class="bk__name">{{ c.label }}</span>
          <span class="bk__reason">{{ c.reason ?? '—' }}</span>
          <button
            type="button"
            class="linkish"
            @click="emit('goto', c.reach === 'large' ? 'validees' : 'matiere')"
          >
            {{ c.reach === 'large' ? 'trancher ses crops' : 'lui trouver des images' }}
          </button>
        </li>
      </ul>
    </div>

    <!-- ── Ce que le dernier run a mesuré ───────────────────────────────── -->
    <div class="meas">
      <h3 class="h3">Ce que le dernier entraînement a mesuré</h3>

      <p v-if="measured.length === 0" class="meas__none">
        Aucune mesure pour cette cohorte : soit aucun benchmark n'a encore tourné,
        soit le ML local est éteint — le taux de reconnaissance et les confusions
        sont calculés sur la machine, pas au serveur.
      </p>

      <template v-else>
        <p class="meas__lede">
          Les moins bonnes d'abord. La colonne <b>confondue avec</b> est celle qui
          compte : deux classes qui se mélangent systématiquement n'en étaient
          peut-être qu'une — c'est le regroupement qu'il faut alors corriger, pas
          le nombre de photos.
          <span v-if="benched" class="mono">· run {{ benched }}</span>
        </p>
        <table class="tbl">
          <thead>
            <tr>
              <th>Classe</th>
              <th class="num">Photos</th>
              <th class="num">R@1</th>
              <th class="num">Δ</th>
              <th>Confondue avec</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in measured" :key="c.class_id">
              <td>
                <div class="tbl__name">{{ labelOf(c.class_id) }}</div>
                <div class="tbl__slug">{{ c.class_id }}</div>
              </td>
              <td class="num mono">{{ c.n_eligible }}</td>
              <td class="num mono" :class="(c.r_at_1 ?? 1) < 0.8 ? 'is-bad' : 'is-ok'">
                {{ pct(c.r_at_1) }}
              </td>
              <td class="num mono" :class="(c.r_at_1_delta ?? 0) < 0 ? 'is-bad' : ''">
                <template v-if="c.r_at_1_delta !== null && c.r_at_1_delta !== 0">
                  {{ c.r_at_1_delta > 0 ? '+' : '' }}{{ Math.round(c.r_at_1_delta * 100) }}
                </template>
                <template v-else>—</template>
              </td>
              <td>
                <span v-if="c.confused_with.length === 0" class="tbl__none">—</span>
                <span v-for="cw in c.confused_with" :key="cw.class_id" class="conf">
                  {{ labelOf(cw.class_id) }} <b>×{{ cw.n }}</b>
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </template>
    </div>

    <!-- ── Les classes que l'augmentation gonfle le plus ────────────────── -->
    <div class="inflate">
      <h3 class="h3">Les classes que l'augmentation gonfle le plus</h3>
      <p class="inflate__say">
        Pour atteindre {{ thresholds.training_target }} images, le bake multiplie
        chaque photo réelle. ×{{ mostInflated[0]?.augFactor ?? 1 }} veut dire que
        {{ Math.max((mostInflated[0]?.augFactor ?? 1) - 1, 0) }} images sur
        {{ mostInflated[0]?.augFactor ?? 1 }} seront des variations de la même
        photo. Ce n'est pas un blocage — c'est ce qu'on relira si ces classes
        se reconnaissent mal.
      </p>
      <ul class="inflate__list">
        <li v-for="c in mostInflated" :key="c.id">
          <span class="inflate__x">×{{ c.augFactor }}</span>
          <span class="inflate__n">{{ c.label }}</span>
          <span class="inflate__seed mono">{{ c.seed }} réelles</span>
        </li>
      </ul>
    </div>

    <p class="captures">
      Les <b>captures device</b> se branchent ici quand elles existent. Elles sont
      optionnelles : leur absence n'empêche pas d'entraîner, elle empêche de
      mesurer sur de vraies photos de téléphone.
      <RouterLink :to="`/lab/cohorts/${cohortId}?tiroir=c2`">Les gérer ↗</RouterLink>
    </p>
  </section>
</template>

<style scoped>
.h {
  font-family: var(--font-display);
  font-size: 19px;
  font-style: italic;
  font-weight: 600;
  margin: 0 0 6px;
}
.h3 {
  font-family: var(--font-display);
  font-size: 16px;
  font-style: italic;
  font-weight: 600;
  margin: 0 0 8px;
}
.mono { font-family: var(--font-mono); font-size: 10px; color: var(--ink-400); }

.verdict {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr) auto;
  gap: 16px;
  align-items: start;
  border: 1px solid var(--surface-3);
  border-radius: 10px;
  padding: 16px 18px;
}
.verdict--go { background: color-mix(in srgb, var(--success) 7%, transparent); border-color: color-mix(in srgb, var(--success) 30%, transparent); }
.verdict--stop { background: color-mix(in srgb, var(--danger) 6%, transparent); border-color: color-mix(in srgb, var(--danger) 26%, transparent); }
.verdict__mark { font-size: 30px; line-height: 1; color: var(--ink-300); }
.verdict--go .verdict__mark { color: var(--success); }
.verdict__say { margin: 0; font-size: 13.5px; color: var(--ink-700); max-width: 72ch; }
.verdict__stale { margin: 9px 0 0; font-size: 12px; color: var(--warning); max-width: 72ch; }
.verdict__seuils { margin: 9px 0 0; font-size: 11.5px; color: var(--ink-500); max-width: 72ch; }

.btn {
  font: inherit;
  font-size: 13px;
  padding: 7px 15px;
  border-radius: 7px;
  text-decoration: none;
  white-space: nowrap;
}
.btn--go { background: var(--indigo-700); color: white; }
.btn--go:hover { background: var(--indigo-800); }

.blockers { margin-top: 16px; }
.blockers__dead { margin: 0 0 10px; font-size: 12.5px; color: var(--danger); }
.blockers__list { list-style: none; margin: 0; padding: 0; }
.blockers__list li {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr) minmax(0, 1.6fr) auto;
  gap: 12px;
  align-items: baseline;
  padding: 8px 0;
  border-bottom: 1px solid var(--surface-2);
}
.bk__tag {
  font-family: var(--font-mono);
  font-size: 8.5px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  padding: 2px 6px;
  border-radius: 4px;
  text-align: center;
}
.bk__tag--block { background: color-mix(in srgb, var(--danger) 14%, transparent); color: var(--danger); }
.bk__tag--warn { background: color-mix(in srgb, var(--warning) 16%, transparent); color: var(--warning); }
.bk__name { font-size: 13px; font-weight: 600; }
.bk__reason { font-size: 11.5px; color: var(--ink-500); }

.linkish {
  background: none;
  border: 0;
  padding: 0;
  font: inherit;
  font-size: 12px;
  color: var(--indigo-700);
  text-decoration: underline;
  cursor: pointer;
  white-space: nowrap;
}

.meas { margin-top: 34px; }
.meas__none { margin: 0; font-size: 12.5px; color: var(--ink-500); max-width: 70ch; }
.meas__lede { margin: 0 0 12px; font-size: 12.5px; color: var(--ink-500); max-width: 78ch; }

.tbl { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.tbl th {
  text-align: left;
  font-family: var(--font-mono);
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: var(--tracking-eyebrow);
  color: var(--ink-400);
  font-weight: 500;
  padding: 0 10px 6px 0;
  border-bottom: 1px solid var(--ink-200);
}
.tbl td { padding: 8px 10px 8px 0; border-bottom: 1px solid var(--surface-2); vertical-align: top; }
.tbl .num { text-align: right; }
.tbl__name { font-weight: 600; }
.tbl__slug { font-family: var(--font-mono); font-size: 9.5px; color: var(--ink-400); }
.tbl__none { color: var(--ink-300); }
.is-bad { color: var(--danger); }
.is-ok { color: var(--success); }
.conf {
  display: inline-block;
  background: var(--surface-2);
  border-radius: 4px;
  padding: 1px 6px;
  margin: 0 5px 4px 0;
  font-size: 11px;
}

.inflate { margin-top: 34px; }
.inflate__say { margin: 0 0 10px; font-size: 12.5px; color: var(--ink-500); max-width: 78ch; }
.inflate__list { list-style: none; margin: 0; padding: 0; }
.inflate__list li {
  display: grid;
  grid-template-columns: 54px minmax(0, 1fr) auto;
  gap: 12px;
  align-items: baseline;
  padding: 5px 0;
  border-bottom: 1px solid var(--surface-2);
}
.inflate__x { font-family: var(--font-mono); font-size: 13px; color: var(--indigo-700); }
.inflate__n { font-size: 12.5px; }
.inflate__seed { white-space: nowrap; }

.captures { margin: 30px 0 0; font-size: 12px; color: var(--ink-500); max-width: 78ch; }
.captures a { color: var(--indigo-700); }

@media (max-width: 900px) {
  .verdict { grid-template-columns: 1fr; }
  .blockers__list li { grid-template-columns: 1fr; gap: 4px; }
}
</style>
