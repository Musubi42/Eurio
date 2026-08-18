<script setup lang="ts">
// Onglet Sourcer — les classes que le tri seul n'amènera pas au plancher :
// celles qui n'ont plus rien à trancher, celles dont le stock est plus petit
// que ce qui manque, et celles qui n'y arriveraient QUE DE JUSTESSE (moins de
// 4 crops ouverts par photo à garder — sous le taux de conservation mesuré).
// On coche, on lance en un geste, on suit le job, on lit le retour en clair.
//
// Deux vérités que cet écran doit dire, sinon il ment :
//   · la découverte eBay se fait par PAYS entier, jamais par pièce — viser une
//     néerlandaise ramène tout le 2 € néerlandais ;
//   · un run peut ramener beaucoup d'images et n'en attribuer aucune à la pièce
//     visée (elles partent sur ses sœurs). D'où `n_attributed_target` affiché
//     à côté du total, et pas à sa place.

import { computed, ref, watch } from 'vue'
import { Loader2 } from 'lucide-vue-next'
import { KEEP_RATIO, type CohortClass } from '@/features/lab/composables/useCohortFloor'
import {
  useCohortJobsQuery,
  useTriggerCoinEbayScrapeMutation,
} from '@/features/lab/composables/useLabQueries'
import type { CohortJob, EbayQuotaInfo } from '@/features/lab/types'

const props = defineProps<{
  cohortId: string
  /** TOUTES les classes sous le plancher — le composant fait le tri lui-même. */
  classes: CohortClass[]
  /** Plancher résolu au canonique — le front n'en définit aucun. */
  floor: number
  quota: EbayQuotaInfo | null
}>()

/** Celles pour qui le tri ne suffira pas (ou tout juste) : le sujet de l'écran. */
const needy = computed(() => props.classes.filter(c => c.reach !== 'large'))
/** Les autres : affichées en second rang, pour montrer POURQUOI on ne les source pas. */
const covered = computed(() => props.classes.filter(c => c.reach === 'large'))

const selected = ref<Set<string>>(new Set())
/** Ce que l'utilisateur a explicitement DÉCOCHÉ — à ne jamais recocher. */
const unchecked = ref<Set<string>>(new Set())
// On observe une clé STABLE, pas le tableau : `needy` est un computed qui rend
// un nouveau tableau à chaque refetch (poll 20 s + refetchOnWindowFocus). En
// observant l'objet, un simple changement d'onglet navigateur recochait les
// classes qu'on venait de retirer — et le récapitulatif de lancement listait
// alors des classes non voulues, avant de consommer le quota eBay dessus.
watch(
  () => needy.value.map(c => c.id).join('|'),
  () => {
    // Pré-cochées : ce sont elles qui ont besoin du scrape. Jamais les
    // couvertes, jamais ce que l'utilisateur a retiré.
    const next = new Set(selected.value)
    for (const c of needy.value) {
      if (!unchecked.value.has(c.id)) next.add(c.id)
    }
    selected.value = next
  },
  { immediate: true },
)
function toggle(id: string) {
  const next = new Set(selected.value)
  const off = new Set(unchecked.value)
  if (next.has(id)) {
    next.delete(id)
    off.add(id)
  } else {
    next.add(id)
    off.delete(id)
  }
  selected.value = next
  unchecked.value = off
}
const nSelected = computed(() => needy.value.filter(c => selected.value.has(c.id)).length)

// Jobs de scrape observables, dernier par pièce visée (trace persistée : le
// badge live seul ne laissait rien derrière lui).
// La query poll déjà toute seule tant qu'un job est `running`.
const jobsQuery = useCohortJobsQuery(() => props.cohortId)
const jobByCoin = computed<Record<string, CohortJob>>(() => {
  const m: Record<string, CohortJob> = {}
  for (const j of jobsQuery.data.value ?? []) {
    if (j.kind !== 'scrape_ebay' || !j.target_eurio_id) continue
    const prev = m[j.target_eurio_id]
    if (!prev || j.started_at > prev.started_at) m[j.target_eurio_id] = j
  }
  return m
})
function jobOf(c: CohortClass): CohortJob | null {
  for (const member of c.members) {
    const j = jobByCoin.value[member]
    if (j) return j
  }
  return null
}
function pct(j: CohortJob): number {
  if (!j.n_total) return 0
  return Math.min(100, Math.round((j.n_done / j.n_total) * 100))
}
/** Ce que le run a réellement rapporté À CETTE CLASSE, dit en clair. */
function outcome(c: CohortClass, j: CohortJob): string {
  if (j.status === 'failed') return j.error ?? 'échec du run'
  // `skipped` = le job n'a PAS tourné. Le lire comme un résultat ferait dire
  // « 0 attribuée, dispersées sur ses sœurs » à un run qui n'a rien cherché.
  if (j.status === 'skipped') return j.note ?? 'run non lancé (rien à faire, ou déjà en cours)'
  if (j.n_attributed_target === 0) {
    return `${j.n_produced} image(s) trouvée(s), 0 attribuée à cette pièce — dispersées sur ses sœurs, à récupérer par la review des lots`
  }
  const stillMissing = Math.max(props.floor - c.have, 0)
  return `+${j.n_attributed_target} image(s) attribuée(s) · il reste ${stillMissing} photo(s) à valider pour franchir le plancher`
}

const scrape = useTriggerCoinEbayScrapeMutation(() => props.cohortId)
const launching = ref(false)

async function launch() {
  const targets = needy.value.filter(c => selected.value.has(c.id))
  if (targets.length === 0) return
  const est = props.quota?.estimate ?? '?'
  const ok = window.confirm(
    `Lancer un scrape eBay sur ${targets.length} classe(s) ?\n\n`
    + `${targets.map(c => `· ${c.label}`).join('\n')}\n\n`
    + `Estimation ~${est} appels Browse API — consomme ton quota eBay.\n`
    + `La découverte se fait par PAYS entier : viser une pièce ramène tout le 2 € du pays.\n`
    + `Le run tourne en arrière-plan ; reviens trancher dans « Trier ».`,
  )
  if (!ok) return
  launching.value = true
  try {
    // Un job par pièce visée : le backend découvre par pays, mais la trace et
    // l'attribution restent par pièce.
    for (const c of targets) {
      const target = c.members[0] ?? c.id
      await scrape.mutateAsync(target)
    }
  } finally {
    launching.value = false
  }
}

const quotaLow = computed(() => props.quota?.ok === false)
</script>

<template>
  <div>
    <div class="bar">
      <button
        type="button"
        class="btn btn--go"
        :disabled="nSelected === 0 || launching || quotaLow"
        @click="launch"
      >
        <Loader2 v-if="launching" class="h-3.5 w-3.5 animate-spin" />
        Scraper {{ nSelected }} classe<span v-if="nSelected > 1">s</span>
      </button>
      <span v-if="quota" class="bar__q">
        ≈ {{ quota.estimate }} appels · quota {{ quota.remaining }} / {{ quota.limit }} restants
      </span>
      <span v-if="quotaLow" class="bar__warn">Quota insuffisant — le bouton est bloqué.</span>
      <span class="bar__note">
        La découverte se fait par pays entier : viser une pièce ramène tout le 2 € du pays.
      </span>
    </div>

    <p v-if="needy.length === 0" class="empty">
      <b>Aucune classe à sourcer.</b> Les {{ covered.length }} classes qui manquent ont
      toutes assez de crops en attente pour atteindre le plancher par le tri seul,
      avec de la marge. Le détail est ci-dessous.
    </p>

    <div v-for="c in needy" :key="c.id" class="row">
      <input
        type="checkbox"
        :checked="selected.has(c.id)"
        :aria-label="`Sélectionner ${c.label}`"
        @change="toggle(c.id)"
      />

      <div class="row__id">
        <div class="row__name">{{ c.label }}</div>
        <div class="row__sub">{{ c.id }}</div>
      </div>

      <div class="row__need">
        <b>{{ c.have }}</b> validées sur {{ floor }}
      </div>

      <div class="row__why" :class="c.reach === 'impossible' ? 'row__why--bad' : 'row__why--thin'">
        <template v-if="c.openSingle + c.openLot === 0">rien à trancher</template>
        <template v-else-if="c.reach === 'impossible'">
          stock {{ c.openSingle + c.openLot }} &lt; {{ c.missing }} manquantes
        </template>
        <template v-else>
          juste — {{ c.openSingle + c.openLot }} en attente pour {{ c.missing }} à valider :
          il faudrait en garder 1 sur {{ Math.floor((c.openSingle + c.openLot) / c.missing) }}
        </template>
      </div>

      <div class="row__job">
        <template v-if="jobOf(c)">
          <div v-if="jobOf(c)!.status === 'running'" class="prog">
            <div class="prog__f" :style="{ width: `${pct(jobOf(c)!)}%` }"></div>
          </div>
          <div class="row__state" :class="{ 'row__state--bad': jobOf(c)!.status === 'failed' }">
            <template v-if="jobOf(c)!.status === 'running'">
              découverte en cours… {{ jobOf(c)!.n_done }}/{{ jobOf(c)!.n_total ?? '?' }}
            </template>
            <template v-else>{{ outcome(c, jobOf(c)!) }}</template>
          </div>
        </template>
        <div v-else class="row__state row__state--idle">jamais scrapée depuis cette cohorte</div>
      </div>
    </div>

    <details v-if="covered.length > 0" class="covered">
      <summary>
        {{ covered.length }} classe<span v-if="covered.length > 1">s</span> couverte<span v-if="covered.length > 1">s</span>
        par le tri — pas besoin de scraper
      </summary>
      <div v-for="c in covered" :key="c.id" class="crow">
        <span class="crow__name">{{ c.label }}</span>
        <span class="crow__n mono">{{ c.have }} validées</span>
        <span class="crow__why mono">
          {{ c.openSingle + c.openLot }} en attente pour {{ c.missing }} à valider —
          il suffirait d'en garder 1 sur {{ Math.floor((c.openSingle + c.openLot) / Math.max(c.missing, 1)) }}
        </span>
      </div>
      <p class="covered__note">
        Une classe remonte en haut s'il faudrait garder mieux qu'une photo sur
        {{ KEEP_RATIO }} pour atteindre le plancher. Ce seuil vient du taux de rejet mesuré
        en juin et juillet (61 % puis 75 %) : c'est une estimation, pas une garantie.
      </p>
    </details>
  </div>
</template>

<style scoped>
.bar {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  padding: 12px 15px;
  border: 1px solid var(--surface-3);
  border-radius: 10px;
  background: var(--surface-1);
  margin-bottom: 18px;
}
.bar__q, .bar__note, .bar__warn {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--ink-500);
}
.bar__note { margin-left: auto; color: var(--ink-400); }
.bar__warn { color: var(--warning); }

.btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 13px;
  font-weight: 500;
  padding: 8px 15px;
  border-radius: 8px;
  border: 1px solid var(--ink-200);
  background: var(--surface);
  color: var(--ink);
  cursor: pointer;
}
.btn--go { background: var(--indigo-700); border-color: var(--indigo-700); color: var(--surface); }
.btn:disabled { opacity: 0.45; cursor: not-allowed; }
.btn:focus-visible { outline: 2px solid var(--gold); outline-offset: 1px; }

.empty { font-size: 13px; color: var(--ink-500); padding: 18px 4px; max-width: 70ch; }
.empty b { color: var(--ink); font-weight: 600; }

.covered { margin-top: 26px; }
.covered summary {
  font-family: var(--font-mono);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: var(--tracking-eyebrow);
  color: var(--ink-400);
  cursor: pointer;
  padding: 6px 0;
}
.covered summary:hover { color: var(--ink); }
.crow {
  display: grid;
  grid-template-columns: 1fr 90px minmax(0, 1.2fr);
  gap: 14px;
  align-items: baseline;
  padding: 7px 13px;
  border-bottom: 1px solid var(--surface-2);
}
.crow__name { font-size: 12.5px; color: var(--ink-700); }
.crow__n { font-size: 11px; color: var(--ink-500); }
.crow__why { font-size: 10px; color: var(--ink-400); }
.covered__note {
  margin-top: 12px;
  font-size: 11.5px;
  color: var(--ink-400);
  max-width: 76ch;
}

.row {
  display: grid;
  grid-template-columns: 26px 1fr 128px 150px minmax(0, 1fr);
  gap: 15px;
  align-items: center;
  padding: 11px 13px;
  border-bottom: 1px solid var(--surface-2);
}
.row:hover { background: var(--surface-1); }
.row input { width: 15px; height: 15px; accent-color: var(--indigo-700); }
.row__id { min-width: 0; }
.row__name { font-size: 13.5px; font-weight: 500; }
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
.row__why { font-family: var(--font-mono); font-size: 10px; line-height: 1.3; }
.row__why--bad { color: var(--danger); }
.row__why--thin { color: var(--warning); }

.prog {
  height: 5px;
  border-radius: 3px;
  background: var(--surface-2);
  overflow: hidden;
  max-width: 260px;
}
.prog__f { height: 100%; background: var(--indigo-400); transition: width 0.4s ease; }
.row__state {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--ink-500);
  margin-top: 5px;
}
.row__state--idle { color: var(--ink-400); margin-top: 0; }
.row__state--bad { color: var(--danger); }

@media (max-width: 900px) {
  .row { grid-template-columns: 24px 1fr; }
  .row__need, .row__why, .row__job { display: none; }
}
@media (prefers-reduced-motion: reduce) {
  .prog__f { transition: none; }
}
</style>
