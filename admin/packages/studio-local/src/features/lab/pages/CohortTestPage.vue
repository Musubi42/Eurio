<script setup lang="ts">
// La page cohorte, refaite en CINQ VUES — bac à sable `/lab/cohorts-test/:id`.
//
// Chaque vue répond à UNE question, produit UN artefact, et ne liste que les
// classes qui n'y sont pas encore. Elles se vident à mesure qu'on avance :
//
//   1 Classes  — qu'est-ce qu'on veut reconnaître ?
//   2 Matière  — a-t-on des images ?
//   3 Crops    — a-t-on des découpes ?
//   4 Validées — lesquelles sont sûres ?     ← là où l'on passe du temps
//   5 Modèle   — est-ce que ça marche ?
//
// Deux règles tiennent tout le reste :
//
// · ON COMPTE EN CLASSES. Le funnel compte par pièce (129 lignes), le contrôle
//   avant entraînement par classe (40). Même question, deux nombres — c'était
//   la première cause de désordre. Ici, la pièce est un détail dépliable.
//
// · AUCUN ÉCRAN NE MENT EN SILENCE. Un compteur qui ne bouge pas dit pourquoi
//   (synchro en attente, crop passé en revers, photo attribuée à une sœur hors
//   cohorte). C'est la leçon la plus chère de la giga-40 : l'interface affichait
//   des états plausibles et faux.
//
// La review n'est PAS réimplémentée : les vues existantes (SingleReviewView /
// LotReviewView) sont montées telles quelles et lisent leur périmètre dans
// l'URL. Aucun fichier de /review n'est modifié — le bandeau cohorte se pose
// au-dessus de leur barre d'actions et appartient à cette page.
//
// Cf. docs/work-in-progress/refacto-page-cohorte/{VISION,FRONT,DECISIONS}.md

import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from 'lucide-vue-next'
import SingleReviewView from '@/features/review/views/SingleReviewView.vue'
import CohortClassList from '@/features/lab/components/CohortClassList.vue'
import CohortCropList from '@/features/lab/components/CohortCropList.vue'
import CohortFinishLine from '@/features/lab/components/CohortFinishLine.vue'
import CohortFloorQueue from '@/features/lab/components/CohortFloorQueue.vue'
import CohortModelPanel from '@/features/lab/components/CohortModelPanel.vue'
import CohortRail, { type CohortView } from '@/features/lab/components/CohortRail.vue'
import CohortReviewStrip from '@/features/lab/components/CohortReviewStrip.vue'
import CohortSourcingList from '@/features/lab/components/CohortSourcingList.vue'
import LotDetailView from '@/features/review/views/LotDetailView.vue'
import { fetchDinoCandidates } from '@/features/review/composables/useReviewApi'
import { fetchLots } from '@/features/review/composables/useLotReview'
import CohortThresholdBar from '@/features/lab/components/CohortThresholdBar.vue'
import { useCohortQuery } from '@/features/lab/composables/useLabQueries'
import { useCohortClasses, type CohortClass } from '@/features/lab/composables/useCohortFloor'

type Mode = 'single' | 'lot'

const route = useRoute()
const router = useRouter()
const cohortId = computed(() => String(route.params.id))

const cohortQuery = useCohortQuery(cohortId)
const cohort = computed(() => cohortQuery.data.value ?? null)

// Classe en main + mode vivent dans l'URL : rechargement et retour arrière
// gardent l'état, et les vues de review y lisent leur périmètre.
const heldId = computed(() => (typeof route.query.classe === 'string' ? route.query.classe : null))
const mode = computed<Mode>(() => (route.query.mode === 'lot' ? 'lot' : 'single'))

const {
  classes, belowFloor, needSourcing, needCrops, sistersLeak, nUnrouted,
  refetchFunnel, quota, lagSeconds, liveCounts, countsSource,
  thresholds, floor, thresholdState, refetchThresholds, thresholdLag,
  preflightThresholds,
  ready, unresolved, nTotal, nMissing, isLoading, error,
} = useCohortClasses(cohortId, { live: computed(() => heldId.value !== null) })

// ── La vue courante ────────────────────────────────────────────────────────
// Dans l'URL, pour que le rechargement et le partage de lien retombent au même
// endroit. À l'arrivée sans paramètre, on ouvre la première vue qui a du
// travail — plutôt que d'obliger à chercher où l'on en est. Figé après le
// premier chargement : la vue ne doit pas sauter sous les doigts.
// ⚠️ Le paramètre s'appelle `etape`, PAS `vue` : `?vue=` est le marqueur interne
// de @vitejs/plugin-vue pour ses sous-requêtes de SFC. Une URL qui le porte fait
// répondre 500 au serveur de dev (« ENOENT … open '/lab/cohorts-test/<id>' »),
// pour une raison qui n'a rien à voir avec l'application.
const VIEWS: CohortView[] = ['classes', 'matiere', 'crops', 'validees', 'modele']
const auto = ref<CohortView | null>(null)
const view = computed<CohortView>(() => {
  const q = route.query.etape
  if (typeof q === 'string' && (VIEWS as string[]).includes(q)) return q as CohortView
  return auto.value ?? 'validees'
})
watch(isLoading, (loading) => {
  if (loading || auto.value) return
  if (needSourcing.value.length > 0) auto.value = 'matiere'
  else if (belowFloor.value.length > 0) auto.value = 'validees'
  else if (needCrops.value.length > 0) auto.value = 'crops'
  else auto.value = 'modele'
}, { immediate: true })

function setView(v: CohortView) {
  // Changer de vue relâche la classe en main : les périmètres de review vivent
  // dans la même query, les traîner ailleurs n'aurait pas de sens.
  void router.replace({ query: { etape: v } })
}

// ── Tri de la review : ordre de file, ou ce que DINO reconnaît ─────────────
// Dans l'URL comme le reste du périmètre — et surtout ré-émis par scopeQuery :
// sans ça, prendre une classe effacerait le réglage.
// « Pêche » allumée = le périmètre de la file devient la PRÉDICTION, et non
// plus la cible du scrape. C'est ce qui rend atteignables les crops de LOTS :
// mesuré sur l'italienne standard, la file par cible en sert 57 dont 2 utiles,
// la pêche 137 tous utiles — dont 136 en lots, invisibles jusqu'ici.
const sortByDino = computed(() => route.query.tri === 'dino')
/** Jusqu'où descendre dans les hypothèses du modèle : 1, 3 ou 5. */
const dinoRank = computed(() => {
  const n = Number.parseInt(String(route.query.dino_rank ?? '1'), 10)
  return [1, 3, 5].includes(n) ? n : 1
})

function setSort(dino: boolean) {
  const q: Record<string, unknown> = { ...route.query }
  if (dino) { q.tri = 'dino' } else { delete q.tri; delete q.dino_rank; delete q.lot }
  void router.replace({ query: q as Record<string, string> })
}
function setRank(rank: number) {
  // Changer de rang change le périmètre : le lot en cours peut ne plus en
  // faire partie. On le relâche plutôt que de garder ouvert un lot que la file
  // ne contient plus — ses voisins seraient alors introuvables.
  const q: Record<string, unknown> = { ...route.query, tri: 'dino' }
  q.dino_rank = String(rank)
  delete q.lot
  void router.replace({ query: q as Record<string, string> })
}

const held = computed<CohortClass | null>(
  () => classes.value.find(c => c.id === heldId.value) ?? null,
)
const nBelow = computed(() => belowFloor.value.length)
const nGreen = computed(() => nTotal.value - nBelow.value)

/** Périmètre passé aux vues de review, reconstruit à chaque prise (jamais cumulé). */
function scopeQuery(k: CohortClass, m: Mode): Record<string, string> {
  const base: Record<string, string> = {
    etape: 'validees', classe: k.id, mode: m, cohort: cohortId.value,
  }
  // Le réglage survit au changement de classe : scopeQuery reconstruit la query
  // ENTIÈRE, donc tout réglage absent d'ici serait perdu à la prise suivante.
  if (sortByDino.value) {
    // PÊCHE — un seul périmètre pour les deux modes : la classe. Il traverse
    // les `kind`, les pays de listing et les cibles de scrape. C'est aussi lui
    // qui donne au « lot suivant » son ordre : sans lui, la nav déroule la file
    // lot globale (5413 items) et sort de la classe au premier clic.
    return { ...base, tri: 'dino', dino_class: k.id, dino_rank: String(dinoRank.value) }
  }
  if (m === 'lot') return { ...base, ...k.lotScope }
  // La file single par cible ne sait filtrer que par pièce. Les classes de la
  // vague 1 n'ont qu'un millésime chacune ; pour une classe multi-millésimes il
  // faudra les enchaîner (limite connue, cf. useCohortFloor).
  return { ...base, eurio_id: k.members[0] ?? k.id }
}

function take(k: CohortClass, m: Mode) {
  void router.replace({ query: scopeQuery(k, m) })
}
function setMode(m: Mode) {
  if (held.value) take(held.value, m)
}
function close() {
  void router.replace({ query: { etape: 'validees' } })
}

/**
 * Classe suivante.
 *   Tour 1 — les classes encore sous le plancher, la plus proche en tête :
 *            c'est le plancher qui débloque l'entraînement.
 *   Tour 2 — plancher atteint partout : les classes que l'augmentation gonfle
 *            le plus (×10 = neuf images sur dix seront des variations de la
 *            même photo). Une grandeur mesurée, pas un plafond décrété.
 */
function nextClass() {
  const notHeld = (c: CohortClass) => c.id !== heldId.value
  const hasStock = (c: CohortClass) => c.openSingle + c.openLot > 0
  const tour1 = belowFloor.value.filter(c => notHeld(c) && hasStock(c))
  const tour2 = classes.value
    .filter(c => notHeld(c) && hasStock(c) && c.have >= floor.value && c.augFactor > 1)
    .sort((a, b) => b.augFactor - a.augFactor)
  const next = tour1[0] ?? tour2[0] ?? null
  if (next) take(next, next.openSingle > 0 ? 'single' : 'lot')
  else close()
}

// Compteurs du périmètre pêché — déclarés ICI parce que `stockNow` les lit et
// qu'un `watch` évalue sa source dès le setup : les laisser plus bas mettrait
// la ref en zone morte temporelle, et la page planterait au montage.
// Ils sont remplis par le watch de la section « pêche », plus bas.
const peche = ref<{ single: number; lot: number; orphans: number } | null>(null)

// Plus rien à trancher sur cette classe → on passe à la suivante. On ne bascule
// PAS sur un compteur atteint : au plancher on est autorisé à partir, jamais
// poussé. Ici c'est différent — il n'y a littéralement plus rien à faire.
//
// ⚠️ Le stock lu doit être celui du PÉRIMÈTRE SERVI. En pêche, les compteurs du
// funnel (par cible) peuvent tomber à zéro alors que la file pêchée est encore
// pleine — sur l'italienne standard, 1 à l'unité par cible contre 137 pêchés.
// Lire le mauvais compteur ferait sauter de classe sous les doigts de quelqu'un
// qui a encore cent crops à trancher.
const stockNow = computed(() => {
  if (!held.value) return -1
  if (sortByDino.value) return peche.value ? peche.value.single + peche.value.lot : -1
  return held.value.openSingle + held.value.openLot
})
watch(stockNow, (stock, before) => {
  if (held.value && stock === 0 && before !== undefined && before > 0) nextClass()
})

// Le stock singles/lots vient du funnel (3,6 s) : on ne le rafraîchit qu'aux
// moments qui comptent — changement de classe ou de mode.
watch([heldId, mode], () => {
  if (heldId.value) void refetchFunnel()
})

// Fraîcheur du compteur. Le chiffre vient d'une copie locale du canonique,
// rafraîchie toutes les `lagSeconds` : sans ça, l'attente ressemble à un
// blocage — c'est le grief remonté au premier essai.
const lastChange = ref(Date.now())
const nowTick = ref(Date.now())
let ticker: ReturnType<typeof setInterval> | null = null
watch(() => held.value?.have, () => { lastChange.value = Date.now() })
const sinceChange = computed(() => Math.round((nowTick.value - lastChange.value) / 1000))

// « P » — classe suivante. Inerte tant que le plancher n'est pas franchi, et
// hors de portée quand on tape dans un champ. S est déjà pris par la review
// lot (requalifier en single), d'où P.
function onKey(e: KeyboardEvent) {
  if (!held.value || e.metaKey || e.ctrlKey || e.altKey) return
  const t = e.target
  if (t instanceof HTMLElement && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable)) return
  if (e.key !== 'p' && e.key !== 'P') return
  if (held.value.have < floor.value) return
  nextClass()
  e.preventDefault()
}
onMounted(() => {
  window.addEventListener('keydown', onKey)
  ticker = setInterval(() => { nowTick.value = Date.now() }, 1000)
})
onUnmounted(() => {
  window.removeEventListener('keydown', onKey)
  if (ticker) clearInterval(ticker)
})

// ── Les lots, un par un ────────────────────────────────────────────────────
// Pas de grille de vignettes : le lot ouvert défile comme l'unité. Valider ou
// skipper enchaîne sur le suivant DU PÉRIMÈTRE, et l'écran s'arrête quand il
// n'y en a plus. Le lot courant vit dans l'URL (`?lot=`) comme le reste du
// périmètre — rechargement et retour arrière retombent au même endroit.
const heldLot = computed(() => {
  const q = route.query.lot
  return typeof q === 'string' && q ? q : null
})

/** Ce qu'on passe à `GET /review-queue/lots{,/{key}}` — le même que la file. */
const lotScope = computed<Record<string, string>>(() => {
  const out: Record<string, string> = {}
  if (!held.value) return out
  if (sortByDino.value) {
    out.dino_class = held.value.id
    out.dino_rank = String(dinoRank.value)
    return out
  }
  const sc = held.value.lotScope
  if ('design_group' in sc) out.design_group = sc.design_group
  else out.target_eurio_id = sc.target
  return out
})

const lotLoading = ref(false)
const lotExhausted = ref(false)

/** Ouvre le premier lot du périmètre. Appelé à l'entrée en mode lot. */
async function openFirstLot() {
  if (!held.value) return
  lotLoading.value = true
  lotExhausted.value = false
  try {
    const resp = await fetchLots({ limit: 1, ...lotScopeArgs() })
    const first = resp.items[0]?.listing_key ?? null
    if (first) void router.replace({ query: { ...route.query, lot: first } })
    else lotExhausted.value = true
  } finally {
    lotLoading.value = false
  }
}

function lotScopeArgs() {
  const sc = lotScope.value
  return {
    dinoClass: sc.dino_class ?? null,
    dinoRank: sc.dino_rank ? Number(sc.dino_rank) : null,
    designGroup: sc.design_group ?? null,
    targetEurioId: sc.target_eurio_id ?? null,
  }
}

function gotoLot(key: string) {
  void router.replace({ query: { ...route.query, lot: key } })
}

/** Plus de lot dans le périmètre : on le dit, et on propose la suite. */
function lotsExhausted() {
  const q = { ...route.query }
  delete q.lot
  lotExhausted.value = true
  void router.replace({ query: q as Record<string, string> })
}

// Entrer en mode lot (ou changer de périmètre) ouvre le premier lot. On ne le
// fait pas quand un lot est déjà à l'écran : ce serait ramener l'opérateur au
// début de la file à chaque refetch.
// ⚠️ On observe `held.value?.id`, PAS `heldId` : `heldId` vient de l'URL et
// vaut déjà quelque chose au premier rendu, alors que la CLASSE n'arrive
// qu'après le chargement du préflight. Observer l'URL ferait passer l'unique
// déclenchement à un moment où `held` est encore nul — l'écran resterait sur
// « Ouverture du premier lot… » pour toujours, sans la moindre erreur.
watch(
  [() => held.value?.id, mode, () => sortByDino.value, dinoRank],
  () => {
    if (mode.value !== 'lot' || !held.value) return
    if (heldLot.value) return
    void openFirstLot()
  },
  { immediate: true },
)

// ── Compteurs du périmètre pêché ───────────────────────────────────────────
// Ceux du funnel comptent le périmètre PAR CIBLE. En pêche, les afficher
// au-dessus d'une file qui sert dix fois plus serait précisément l'écran
// plausible et faux que cette page existe pour ne plus produire.
watch(
  [heldId, () => sortByDino.value, dinoRank],
  async () => {
    if (!heldId.value || !sortByDino.value) { peche.value = null; return }
    const s = await fetchDinoCandidates(heldId.value, { rank: dinoRank.value })
    // `null` = le canonique n'a pas répondu. On garde `null` plutôt que des
    // zéros : un zéro faux désactiverait les boutons et dirait « classe vide ».
    peche.value = s
      ? { single: s.n_open_single, lot: s.n_open_lot, orphans: s.n_orphans }
      : null
  },
  { immediate: true },
)

const reviewBox = ref<HTMLElement | null>(null)
watch(heldId, (id) => {
  if (id) void Promise.resolve().then(() => reviewBox.value?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
})
</script>

<template>
  <div class="page" :class="{ 'page--wide': held }">
    <RouterLink class="back" :to="`/lab/cohorts/${cohortId}`">
      <ArrowLeft class="h-3 w-3" /> Retour à la cohorte
    </RouterLink>

    <p v-if="error" class="err">{{ error }}</p>
    <p v-else-if="isLoading" class="loading">Lecture du contrôle avant entraînement…</p>

    <template v-else>
      <div class="eyebrow">
        Cohort · {{ cohortId }}<span v-if="cohort"> · {{ cohort.name }}</span>
      </div>

      <CohortRail
        :cohort-id="cohortId"
        :view="view"
        :classes="classes"
        :below-floor="belowFloor"
        :need-sourcing="needSourcing"
        :need-crops="needCrops"
        :n-missing="nMissing"
        :ready="ready"
        @view="setView"
      />

      <!-- L'en-tête commun aux 5 vues : où en est la cohorte, et sous quelle
           règle. Le plancher se règle ici, avec sa provenance et son histoire. -->
      <CohortThresholdBar
        :cohort-id="cohortId"
        :thresholds="thresholds"
        :state="thresholdState"
        :lag="thresholdLag"
        @changed="() => { refetchThresholds(); }"
      />

      <section class="verdict">
        <div>
          <div class="eyebrow">Avant de pouvoir entraîner</div>
          <div class="count">
            <em>{{ nBelow }}</em><span class="count__of">/{{ nTotal }}</span>
          </div>
          <!-- Une cohorte dont aucune pièce ne résout donne 0 classe : dire
               « toutes ont franchi le plancher » en gros caractères, juste
               au-dessus de « contrôle · refuse », serait la contradiction la
               plus visible de la page. -->
          <p v-if="nTotal === 0" class="verdict__say">
            <b>Aucune classe résolue</b> pour cette cohorte. Ses pièces n'existent
            pas au catalogue, ou elle est vide — rien ne peut être entraîné en
            l'état.
            <button type="button" class="linkish" @click="setView('classes')">
              Voir la composition
            </button>
          </p>
          <p v-else-if="nBelow === 0" class="verdict__say">
            <b>Toutes les classes</b> ont franchi le plancher de {{ floor }} photos réelles.
          </p>
          <p v-else class="verdict__say">
            <b>{{ nBelow }} classe{{ nBelow > 1 ? 's' : '' }}</b>
            n'{{ nBelow > 1 ? 'ont' : 'a' }} pas atteint {{ floor }} photos réelles.
            Les {{ nGreen }} autres sont prêtes. Il reste <b>{{ nMissing }}</b> photos à valider.
          </p>
          <p class="verdict__meta mono">
            contrôle · {{ ready ? 'passe' : 'refuse' }}
            · compteur {{ liveCounts ? 'en direct du serveur' : `copie locale, ${lagSeconds}s de retard max` }}
            <span v-if="needSourcing.length > 0">
              · {{ needSourcing.length }} sans matière à trancher
            </span>
          </p>
        </div>

        <CohortFinishLine :classes="classes" :floor="floor" />
      </section>

      <!-- ── VUE 1 · Classes ─────────────────────────────────────────────── -->
      <section v-if="view === 'classes'" class="panel">
        <CohortClassList
          :cohort-id="cohortId"
          :classes="classes"
          :floor="floor"
          :unresolved="unresolved"
        />
      </section>

      <!-- ── VUE 2 · Matière ─────────────────────────────────────────────── -->
      <section v-else-if="view === 'matiere'" class="panel">
        <div v-if="needSourcing.length === 0" class="done">
          <b>Rien à sourcer.</b> Toutes les classes sous le plancher ont déjà
          assez de crops en attente pour l'atteindre par le tri seul — aller
          chercher plus d'images eBay coûterait du quota sans rien débloquer.
          <button type="button" class="linkish" @click="setView('validees')">
            Aller trancher
          </button>
        </div>
        <CohortSourcingList
          v-else
          :cohort-id="cohortId"
          :classes="belowFloor"
          :floor="floor"
          :quota="quota"
        />
      </section>

      <!-- ── VUE 3 · Crops ───────────────────────────────────────────────── -->
      <section v-else-if="view === 'crops'" class="panel">
        <CohortCropList
          :cohort-id="cohortId"
          :classes="needCrops"
          :sisters="sistersLeak"
        />
      </section>

      <!-- ── VUE 5 · Modèle ──────────────────────────────────────────────── -->
      <section v-else-if="view === 'modele'" class="panel">
        <CohortModelPanel
          :cohort-id="cohortId"
          :classes="classes"
          :below-floor="belowFloor"
          :unresolved="unresolved"
          :ready="ready"
          :thresholds="thresholds"
          :used-thresholds="preflightThresholds"
          @goto="setView"
        />
      </section>

      <!-- ── VUE 4 · Validées ────────────────────────────────────────────── -->
      <template v-else>
        <!-- Review montée dans la page : les vues existantes, inchangées. -->
        <section v-if="held" ref="reviewBox" class="review">
          <div class="review__frame">
            <SingleReviewView v-if="mode === 'single'" :key="`s-${held.id}`" />
            <LotDetailView
              v-else-if="heldLot"
              :key="`l-${heldLot}`"
              :listing-key="heldLot"
              :scope="lotScope"
              @navigate="gotoLot"
              @exhausted="lotsExhausted"
            />
            <p v-else-if="lotLoading" class="lotmsg">Ouverture du premier lot…</p>
            <p v-else-if="lotExhausted" class="lotmsg">
              <b>Plus de lot à trancher</b> dans ce périmètre.
              <button type="button" class="linkish" @click="setMode('single')">
                Passer à l'unité
              </button>
              <template v-if="!sortByDino">
                · ou allumer la <b>pêche DINO</b> pour atteindre les lots que le
                scrape ne visait pas.
              </template>
            </p>
          </div>
          <CohortReviewStrip
            :klass="held"
            :floor="floor"
            :mode="mode"
            :sort-by-dino="sortByDino"
            :dino-rank="dinoRank"
            :peche="peche"
            :since-change="sinceChange"
            :source="countsSource"
            :lag-seconds="lagSeconds"
            @sort="setSort"
            @rank="setRank"
            @next="nextClass"
            @mode="setMode"
            @close="close"
          />
        </section>

        <section class="queue">
          <div class="queue__h">
            <h2 class="queue__t">La file</h2>
            <span class="eyebrow">classée par la plus rapide à débloquer</span>
          </div>
          <CohortFloorQueue
            :classes="belowFloor"
            :floor="floor"
            :held-id="heldId"
            @take="take"
          />

          <!-- Le stock invisible : ni tranché, ni en file. 33 crops sur la
               giga-40. Le taire, c'est le perdre. -->
          <p v-if="nUnrouted !== null && nUnrouted > 0" class="queue__leak">
            ⚠ <b>{{ nUnrouted }} crop{{ nUnrouted > 1 ? 's' : '' }}</b>
            {{ nUnrouted > 1 ? 'sont' : 'est' }} en attente de review mais
            n'apparaî{{ nUnrouted > 1 ? 'ssent' : 't' }} dans aucune file — ni
            tranché{{ nUnrouted > 1 ? 's' : '' }}, ni visible{{ nUnrouted > 1 ? 's' : '' }}.
            Ils sortent du décompte « en attente » ci-dessus.
          </p>
          <!-- Ce décompte ne vient QUE du canonique. Tant qu'il n'a pas
               répondu, se taire reviendrait à affirmer qu'il n'y a rien —
               c'est-à-dire à rendre invisibles, une seconde fois, les crops
               dont cet encart existe pour signaler l'invisibilité. -->
          <p v-else-if="nUnrouted === null" class="queue__unknown">
            Les crops bloqués hors file se comptent au serveur, qui n'a pas encore
            répondu — ce décompte est inconnu, pas nul.
          </p>

          <p v-if="needSourcing.length > 0" class="queue__hint">
            {{ needSourcing.length }} classe{{ needSourcing.length > 1 ? 's' : '' }}
            n'{{ needSourcing.length > 1 ? 'ont' : 'a' }} pas assez de crops en attente pour
            atteindre le plancher —
            <button type="button" class="linkish" @click="setView('matiere')">à sourcer</button>.
          </p>
        </section>
      </template>
    </template>
  </div>
</template>

<style scoped>
/* 1180 px : la bonne largeur pour lire du texte — c'est la page au repos.
 *
 * Mais dès qu'une classe est en main, la review devient un poste de travail :
 * sélection libre (pays + dénomination + grille de candidats), suggestions
 * DINO, planche de lot. À 1180 px tout s'y tasse pendant que l'écran reste
 * vide de chaque côté. La page s'élargit donc en mode review.
 *
 * Élargir LA PAGE plutôt que faire déborder la review de sa colonne : un
 * full-bleed en `100vw` compterait la barre de navigation dans sa largeur et
 * passerait dessous (mesuré — le panneau de droite sortait de l'écran). Ici
 * c'est le conteneur de l'application qui borne, donc rien ne peut déborder. */
.page {
  max-width: 1180px;
  margin: 0 auto;
  padding: 26px 26px 80px;
  transition: max-width 0.25s ease, padding 0.25s ease;
}
.page--wide { max-width: 1720px; padding-left: 16px; padding-right: 16px; }
@media (prefers-reduced-motion: reduce) {
  .page { transition: none; }
}
.back {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: var(--font-mono);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--ink-500);
  text-decoration: none;
  margin-bottom: 18px;
}
.back:hover { color: var(--ink); }
.err { color: var(--danger); font-size: 13px; }
.loading { color: var(--ink-400); font-size: 13px; }

.eyebrow {
  font-family: var(--font-mono);
  font-size: 9.5px;
  text-transform: uppercase;
  letter-spacing: var(--tracking-eyebrow);
  color: var(--ink-400);
}

.verdict {
  display: grid;
  grid-template-columns: minmax(0, 300px) 1fr;
  gap: 44px;
  align-items: end;
  margin: 16px 0 30px;
}
.count {
  font-family: var(--font-display);
  font-size: 82px;
  line-height: 0.86;
  font-weight: 600;
  letter-spacing: -0.04em;
}
.count em { font-style: italic; color: var(--gold-700); }
.count__of { font-size: 38px; color: var(--ink-300); }
.verdict__say { font-size: 14.5px; color: var(--ink-700); margin-top: 12px; max-width: 36ch; }
.verdict__say b { font-weight: 600; }
.verdict__meta { font-size: 10px; color: var(--ink-400); margin-top: 8px; }
.mono { font-family: var(--font-mono); }

.panel { padding-top: 6px; }
.done {
  border: 1px solid color-mix(in srgb, var(--success) 32%, transparent);
  background: color-mix(in srgb, var(--success) 7%, transparent);
  border-radius: 9px;
  padding: 14px 16px;
  font-size: 13px;
  color: var(--ink-700);
  max-width: 78ch;
}

.review {
  margin-top: 10px;
  border: 1px solid var(--ink-200);
  border-radius: 12px;
  overflow: hidden;
  background: var(--surface);
}
/* Les vues de review sont conçues pleine hauteur : on leur donne un cadre net
   et défilable plutôt que de les laisser étirer la page. La hauteur suit le
   viewport (et non un pixel fixe) : c'est la place réelle qu'on a. */
.review__frame {
  display: flex;
  flex-direction: column;
  height: min(88vh, 1200px);
  min-height: 560px;
  overflow: auto;
}

.lotmsg {
  padding: 40px 24px;
  font-size: 13.5px;
  color: var(--ink-500);
  max-width: 74ch;
  line-height: 1.55;
}
.lotmsg b { color: var(--ink); font-weight: 600; }

.linkish {
  background: none;
  border: 0;
  padding: 0;
  font: inherit;
  color: var(--indigo-700);
  text-decoration: underline;
  cursor: pointer;
}

.queue { margin-top: 30px; }
.queue__hint { margin-top: 12px; font-size: 12px; color: var(--ink-500); }
.queue__unknown { margin-top: 14px; font-size: 12px; color: var(--ink-400); max-width: 80ch; }
.queue__leak {
  margin-top: 14px;
  font-size: 12.5px;
  color: var(--ink-700);
  background: color-mix(in srgb, var(--warning) 9%, transparent);
  border: 1px solid color-mix(in srgb, var(--warning) 30%, transparent);
  border-radius: 8px;
  padding: 9px 13px;
  max-width: 80ch;
}
.queue__h { display: flex; align-items: baseline; gap: 12px; margin-bottom: 11px; }
.queue__t {
  font-family: var(--font-display);
  font-size: 17px;
  font-style: italic;
  font-weight: 600;
  margin: 0;
}

@media (max-width: 820px) {
  .verdict { grid-template-columns: 1fr; gap: 20px; align-items: start; }
}
</style>
