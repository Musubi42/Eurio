<script setup lang="ts">
// La moitié ACHETER de `/besoin` (lot 5) : ce qui manque, par groupe de
// découverte, ce que ça coûterait, et le quota restant.
//
// ⛔ LE GESTE EST UN LIEN VERS UN PLAN, JAMAIS UN LANCEMENT. Le plan s'ouvre en
// lecture (l'allocateur en dry-run) et porte sa propre commande ; l'exécuter
// reste un geste de terminal, explicite, qui consomme de l'argent réel.
//
// ⛔ LES DEUX RÉSERVES SONT À L'ÉCRAN, PAS DANS UN COMMENTAIRE (FLOW-ADMIN
// §Station 1 : « sinon la station ment ») : le préflight quota de
// `sources/cli.py` est faux d'un facteur ~130, et le budget vrai est dans
// `eurio.local.db`, pas au canonique. Elles viennent du back, qui les tient de
// `scrape_plan_routes.RESERVES` — les recopier ici les ferait diverger.
//
// ⛔ AUCUN CHIFFRE N'EST CALCULÉ ICI. Le seul nombre qui ne vient pas de
// `/scrape-plan` est « à aller chercher », qui vient de `/class-need` — et il
// est passé en prop, pas recalculé.
//
// Bloc LOURD dans une page qui ne l'est PAS : `/besoin` s'affiche entièrement
// en hébergé, et c'est ce bloc-ci, seul, qui se grise.

import { computed, onMounted, watch } from 'vue'

import LocalOnlyNotice from '@/shared/ui/LocalOnlyNotice.vue'
import { shellCommand, useScrapePlan } from '../composables/useScrapePlan'

const props = defineProps<{
  /** `sum_need - sum_reachable` de `/class-need` — lisible même en hébergé. */
  aChercher: number
  /** Classes à goulot `scrape`, d'après `/class-need`. */
  nClassesScrape: number
  heavyLocked: boolean
}>()

const {
  summary, loading, error, load,
  plan, planFor, planLoading, planError, loadPlan, closePlan,
} = useScrapePlan()

const q = computed(() => summary.value?.quota ?? null)
const y = computed(() => summary.value?.measured_yield ?? null)

/** L'écart au repère du design. Affiché comme un ÉCART, pas comme un désaccord :
 *  le rendement bouge à chaque rebuild de banque. */
const ecartRendement = computed(() => {
  const m = y.value
  if (!m || m.listings_per_exemplar === null) return null
  return Math.round((m.listings_per_exemplar - m.reference) * 100) / 100
})

function fmt(n: number | null | undefined): string {
  return n === null || n === undefined ? '—' : n.toLocaleString('fr-FR')
}

onMounted(() => {
  if (!props.heavyLocked) void load()
})
// Le ping `:8042` de `useCapabilities` arrive après le montage : on charge dès
// que la capacité bascule, sinon le bloc reste vide alors que l'API est là.
watch(() => props.heavyLocked, (locked) => {
  if (!locked && !summary.value && !loading.value) void load()
})
</script>

<template>
  <div class="panel panel--heavy">
    <span class="eyebrow">
      Acheter
      <span v-if="heavyLocked" class="local">· local seulement</span>
    </span>
    <span class="big">{{ fmt(aChercher) }}<small> à aller chercher</small></span>

    <!-- HÉBERGÉ (ou API ML éteinte) : le bloc se grise et le DIT. Le reste de
         la page, lui, s'affiche entièrement — la route n'est pas `heavy`. -->
    <div v-if="heavyLocked" class="slot">
      <p class="sub">
        {{ fmt(nClassesScrape) }} classes sans aucun candidat. Le chiffrage
        (groupes de découverte, coût, quota du jour) lit
        <code>ml/state/eurio.local.db</code>, qui n'existe que sur la machine
        qui scrape.
      </p>
      <LocalOnlyNotice />
    </div>

    <!-- ERREUR : jamais un bloc vide. « Rien à acheter » est plausible et faux. -->
    <div v-else-if="error" class="err">
      <b>Le plan de scrape n'a pas répondu.</b>
      <p class="mono">{{ error }}</p>
      <p>
        La route est <code>GET /scrape-plan/summary</code> sur l'API ML locale.
        <button type="button" class="linkish" @click="load()">Réessayer</button>
      </p>
    </div>

    <div v-else-if="loading && !summary" class="sub">
      Lecture du besoin de scrape et du quota local…
    </div>

    <template v-else-if="summary">
      <ul class="sub list">
        <li>
          <b>{{ fmt(summary.totals.n_classes) }} classes</b> sans aucun candidat ·
          {{ fmt(summary.totals.n_groups) }} groupes de découverte
        </li>
        <li>
          <b>{{ fmt(summary.totals.n_never_targeted) }} n'ont JAMAIS été visées</b>
          par une annonce eBay ·
          {{ fmt(summary.totals.n_targeted_no_result) }} l'ont été sans résultat
          <span class="tiny">(celles-là ne se réparent pas en rescrapant)</span>
        </li>
        <li v-if="y">
          palier 1 : {{ fmt(summary.totals.n_never_targeted) }} × 1 exemplaire ≈
          <b>{{ fmt(summary.totals.estimated_listings_palier1) }} annonces</b>
          · <b>{{ fmt(summary.totals.estimated_calls) }} appels</b> de quota
        </li>
      </ul>

      <!-- Le rendement porte sa mesure, et l'écart au repère se lit comme un
           écart : la banque bouge, les chiffres avec elle. -->
      <p v-if="y" class="meta">
        rendement <b>{{ y.listings_per_exemplar ?? '—' }}</b> annonce(s) par exemplaire
        — <code>{{ fmt(y.n_listings) }}</code> annonces eBay (grain listing) /
        <code>{{ fmt(y.n_exemplars) }}</code> exemplaires <code>fps</code>
        <span v-if="ecartRendement !== null" class="tiny">
          · repère du 22/08 : {{ y.reference }} ({{ y.reference_listings }} /
          {{ y.reference_exemplars }}) —
          écart {{ ecartRendement > 0 ? '+' : '' }}{{ ecartRendement }}
        </span>
      </p>

      <!-- Le quota, avec le fichier lu : c'est la réserve n°2, rendue vérifiable. -->
      <p class="quota" :class="{ 'quota--ko': !q?.readable }">
        <template v-if="q?.readable">
          quota eBay <b>{{ fmt(q.calls) }} / {{ fmt(q.limit) }}</b> appels utilisés
          le {{ q.period }} · reste {{ fmt(q.remaining) }} ·
          <b>{{ fmt(q.safe_budget) }} planifiables</b> (marge ×{{ q.safety_factor }})
          <span class="tiny">lu dans <code>{{ q.db_path }}</code></span>
        </template>
        <template v-else>
          <b>Quota illisible</b> — budget forcé à 0, jamais supposé plein.
          <span class="mono">{{ q?.error }}</span>
        </template>
      </p>

      <!-- Par pays : la colonne « jamais visées » est celle qui décide. -->
      <table class="tbl">
        <thead>
          <tr>
            <th>pays</th><th>classes</th><th>jamais visées</th>
            <th>groupes</th><th>appels</th><th>annonces</th><th />
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="c in summary.countries.slice(0, 10)" :key="c.country"
            :class="{ 'row--on': planFor === c.country }"
          >
            <td class="mono"><b>{{ c.country }}</b></td>
            <td class="num">{{ fmt(c.n_classes) }}</td>
            <td class="num">
              {{ fmt(c.n_never_targeted) }}
              <span v-if="c.n_targeted_no_result" class="tiny">
                (+{{ c.n_targeted_no_result }} sans résultat)
              </span>
            </td>
            <td class="num">
              {{ fmt(c.n_groups) }}
              <span v-if="c.n_groups_standard" class="tiny">dont {{ c.n_groups_standard }} std</span>
            </td>
            <td class="num">{{ fmt(c.estimated_calls) }}</td>
            <td class="num">{{ fmt(c.estimated_listings_palier1) }}</td>
            <td>
              <button
                type="button" class="linkish" :disabled="planLoading"
                :title="`Ouvre le plan de l'allocateur pour ${c.country}. Lecture seule — rien n'est lancé.`"
                @click="loadPlan(c.country)"
              >
                plan {{ c.country }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>

      <!-- Les réserves viennent du back : les recopier ici les ferait diverger. -->
      <p v-for="r in summary.reserves" :key="r" class="reserve">{{ r }}</p>

      <div class="actions">
        <button
          type="button" class="btn" :disabled="planLoading"
          title="Ouvre le plan complet de l'allocateur, tous pays. Lecture seule."
          @click="loadPlan(null)"
        >
          {{ planLoading ? 'Lecture du plan…' : 'Ouvrir le plan de scrape' }}
        </button>
        <code class="cmd">{{ shellCommand(summary.plan_command) }}</code>
      </div>

      <!-- LE PLAN. Il s'affiche ; il ne part pas. -->
      <div v-if="planError" class="err">
        <b>Le plan n'a pas pu être lu.</b>
        <p class="mono">{{ planError }}</p>
      </div>

      <div v-else-if="plan" class="plan">
        <div class="plan-head">
          <b>Plan {{ plan.country ?? 'complet' }}</b>
          <span class="tiny">
            {{ fmt(plan.n_groups) }} groupes · {{ fmt(plan.cost) }} appels sur un
            budget de {{ fmt(plan.budget) }} ({{ plan.budget_source }})
          </span>
          <button type="button" class="linkish" @click="closePlan()">fermer</button>
        </div>

        <p v-if="!plan.groups.length" class="sub">
          Aucun groupe finançable ici — budget épuisé, cooldown, ou
          <code>empty_upstream</code> déjà connu. Un plan vide n'est pas une
          panne : c'est un refus, et il est motivé ci-dessous.
        </p>

        <ol v-else class="groups">
          <li v-for="g in plan.groups" :key="`${g.country}-${g.year ?? 'std'}`">
            <span class="mono"><b>{{ g.country }}/{{ g.year ?? 'std' }}</b></span>
            <span class="tiny">{{ g.kind === 'standard' ? 'standard' : 'commémo' }}</span>
            <span>{{ g.n_classes_needing }} classes · {{ g.need }} exemplaires ·
              {{ g.n_zero }} à zéro</span>
            <span class="tiny">{{ g.cost }} appels · score {{ g.score }}</span>
          </li>
        </ol>

        <p class="tiny skipped">
          écartés — cooldown {{ plan.skipped.cooldown.length }} ·
          empty_upstream {{ plan.skipped.empty_upstream.length }} ·
          hors budget {{ plan.skipped.over_budget.length }} ·
          couverts par la review {{ plan.review_covered_classes.length }}
        </p>

        <p class="warn">
          Ce plan ne lance rien. Chacune de ces commandes consomme du quota eBay
          réel — elles se collent dans un terminal, à la main.
        </p>
        <code v-for="(cmd, i) in plan.commands" :key="i" class="cmd">{{ shellCommand(cmd) }}</code>
      </div>
    </template>
  </div>
</template>

<style scoped>
.panel {
  display: flex; flex-direction: column;
  background: var(--surface-1); border: 1px solid var(--surface-3);
  border-radius: 12px; padding: 16px; text-align: left;
}
.panel--heavy {
  background: repeating-linear-gradient(135deg, var(--surface-1), var(--surface-1) 9px,
    var(--surface-2) 9px, var(--surface-2) 18px);
}
.eyebrow {
  font-size: 10px; text-transform: uppercase; letter-spacing: 0.2em;
  color: var(--ink-400); font-weight: 600;
}
.local { text-transform: none; letter-spacing: 0; color: var(--ink-300); }
.big {
  font-family: var(--font-mono); font-size: 25px; color: var(--ink);
  letter-spacing: -0.02em; margin: 8px 0 4px;
}
.big small { font-size: 13px; color: var(--ink-400); }
.sub { font-size: 11.5px; color: var(--ink-500); }
.sub b { color: var(--ink); }
.tiny { font-size: 10.5px; color: var(--ink-400); }
.list { list-style: none; margin: 8px 0 10px; }
.list li { padding: 1px 0; }
.mono { font-family: var(--font-mono); }

/* La notice locale est conçue plein écran : ici elle vit dans une demi-colonne. */
.slot { margin-top: 8px; }
.slot :deep(.local-only) { min-height: auto; padding: 8px 0 0; }
.slot :deep(.card) { text-align: left; max-width: none; }

.meta { font-size: 10.5px; color: var(--ink-400); margin: 2px 0 8px; }
.meta b { color: var(--ink); font-family: var(--font-mono); }

.quota {
  font-size: 11px; color: var(--ink-500); background: var(--surface-2);
  border-radius: 8px; padding: 7px 10px; margin-bottom: 10px;
}
.quota b { color: var(--ink); font-family: var(--font-mono); }
.quota--ko { color: var(--danger); }
.quota .tiny { display: block; margin-top: 3px; }

.tbl { width: 100%; border-collapse: collapse; font-size: 11px; margin-bottom: 10px; }
.tbl th {
  text-align: left; font-size: 9.5px; text-transform: uppercase;
  letter-spacing: 0.12em; color: var(--ink-400); font-weight: 600;
  border-bottom: 1px solid var(--surface-3); padding: 3px 6px 3px 0;
}
.tbl td { padding: 3px 6px 3px 0; color: var(--ink-500); vertical-align: top; }
.tbl td b { color: var(--ink); }
.row--on td { background: var(--surface-2); }
.num { font-family: var(--font-mono); }

.reserve {
  font-size: 11px; color: var(--warning);
  border-left: 2px solid var(--warning); padding-left: 8px; margin: 0 0 8px;
}
.warn {
  font-size: 11px; color: var(--warning); margin: 10px 0 6px; font-weight: 500;
}
.err { border-left: 3px solid var(--danger); padding-left: 12px; font-size: 11.5px; color: var(--ink-500); margin: 8px 0; }
.err b { color: var(--ink); }

.actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 4px; }
.btn {
  font-size: 12.5px; font-weight: 500; padding: 7px 14px; border-radius: 8px;
  border: 1px solid var(--indigo-700); background: var(--indigo-700);
  color: var(--surface); cursor: pointer;
}
.btn:disabled { opacity: 0.5; cursor: wait; }
.linkish {
  font-size: 11.5px; color: var(--indigo-700); text-decoration: underline;
  text-underline-offset: 2px; cursor: pointer; background: none; border: none; padding: 0;
}
.linkish:disabled { opacity: 0.5; cursor: wait; }

.plan { margin-top: 12px; border-top: 1px solid var(--surface-3); padding-top: 10px; }
.plan-head { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; font-size: 12px; }
.plan-head b { color: var(--ink); }
.groups { list-style: decimal; margin: 8px 0 8px 20px; font-size: 11px; color: var(--ink-500); }
.groups li { padding: 1px 0; display: flex; gap: 10px; flex-wrap: wrap; }
.skipped { margin-bottom: 6px; }
.cmd {
  display: block; font-family: var(--font-mono); font-size: 10.5px;
  background: var(--surface-2); border-radius: 6px; padding: 6px 8px;
  color: var(--ink-500); overflow-x: auto; white-space: pre; margin-top: 4px;
}
code {
  font-family: var(--font-mono); font-size: 10.5px;
  background: var(--surface-2); border-radius: 3px; padding: 0 3px;
}
</style>
