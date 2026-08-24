<script setup lang="ts">
// La pêche — `/review/peche?class=<class_id>`.
//
// Une file de review définie par ce que la banque RECONNAÎT, et non par ce que
// le scrape visait. Même mécanisme que dans la page cohorte, sans la cohorte :
// on entre par la page d'une pièce (« DINO a repéré N crops pour cette
// classe ») ou par une URL, on nourrit la classe, on repart.
//
// Pourquoi cette page existe séparément du bandeau cohorte : nourrir une classe
// n'a rien à voir avec finir une cohorte. Une classe pauvre se nourrit quand on
// tombe dessus, souvent des semaines avant qu'une cohorte la réclame — et à ce
// moment-là il n'y a pas de cohorte ouverte à laquelle se raccrocher.
//
// Mesure de référence (2026-08-20) : sur `it-2euro-standard-t1`, la file par
// cible sert 57 items dont 2 utiles ; la pêche en sert 137, tous de la classe,
// dont 136 en lots — inatteignables autrement.

import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from 'lucide-vue-next'
import SingleReviewView from '../views/SingleReviewView.vue'
import LotDetailView from '../views/LotDetailView.vue'
import PecheBar from '../components/PecheBar.vue'
import { useLotChain } from '../composables/useLotChain'
import { queryNeedOnly, queryParam } from '../composables/useQueryScope'
import {
  fetchDinoCandidates, type DinoCandidatesSummary,
} from '../composables/useReviewApi'
import { reflagAssetsNeedsReview } from '@/features/coins/composables/useCoinAssets'
import { useHeavyGate } from '@/shared/composables/useHeavyGate'

// Le lien de retour suit la porte par laquelle on est ENTRÉ : un ami vient
// de « Trier » sur son accueil, un opérateur vient de la file. `review:arbitrate`
// est le même discriminant que partout ailleurs dans ce front (D11).
const { canArbitrate } = useHeavyGate()
const route = useRoute()
const router = useRouter()

// ── Le périmètre vit dans l'URL, entièrement ──────────────────────────────
// Partager le lien, recharger, revenir en arrière : on retombe sur la même
// file. C'est aussi ce qui permet à la page d'une pièce de pointer ici sans
// rien passer d'autre qu'une URL.
const classId = computed(() => queryParam(route, 'class') ?? '')
const rank = computed(() => {
  const n = Number.parseInt(queryParam(route, 'dino_rank') ?? '1', 10)
  return [1, 3, 5].includes(n) ? n : 1
})
const minSpread = computed<number | null>(() => {
  const raw = queryParam(route, 'dino_min')
  if (!raw) return null
  const n = Number.parseFloat(raw)
  return Number.isFinite(n) ? n : null
})
// Filtre pays — ACTIF par défaut, et l'URL ne porte que la LEVÉE (`pays=tous`).
// Un défaut qui ne s'écrit pas dans l'URL garde les liens courts et rend le
// réglage non-défaut visible d'un coup d'œil dans la barre d'adresse.
const countryOnly = computed(() => queryParam(route, 'pays') !== 'tous')
// Périmètre PAR BESOIN — actif par défaut (D9). La pêche ne le passait PAS,
// donc elle servait les classes pleines : 4 999 des 6 574 crops ouverts.
// `queryNeedOnly` porte le défaut ; ici on ne fait que le relayer aux lots et
// au résumé (les vues single le lisent elles-mêmes dans la route).
const needOnly = computed(() => queryNeedOnly(route))

// ⛔ Le mode LOT est réservé à l'arbitre (`funnel_writes.decide_lot` exige
// `review:arbitrate` depuis le 2026-08-24, faute de quarantaine sur les lots).
// `PecheBar` en masque déjà l'onglet ; on referme ici le chemin de l'URL tapée à
// la main, sinon un ami atterrit sur une vue de lot dont chaque geste rend 403.
// C'est du confort, comme tout le filtrage front — la garde est serveur.
const mode = computed<'single' | 'lot'>(
  () => (queryParam(route, 'mode') === 'lot' && canArbitrate.value ? 'lot' : 'single'),
)
/** L'opérateur a-t-il CHOISI son mode, ou est-ce le défaut ? */
const modeChosen = computed(() => queryParam(route, 'mode') !== null)

function patch(next: Record<string, string | undefined>) {
  const q: Record<string, unknown> = { ...route.query, ...next }
  for (const [k, v] of Object.entries(next)) if (v === undefined) delete q[k]
  void router.replace({ query: q as Record<string, string> })
}
// Changer de rang, de marge ou de classe change le PÉRIMÈTRE : le lot ouvert
// peut ne plus en faire partie. On le relâche — garder à l'écran un lot que la
// file ne contient plus rendrait ses voisins introuvables, et « suivant »
// muet.
function setRank(r: number) { patch({ dino_rank: String(r), lot: undefined }) }
function setMinSpread(v: number | null) {
  patch({ dino_min: v == null ? undefined : String(v), lot: undefined })
}
function setMode(m: 'single' | 'lot') { patch({ mode: m, lot: undefined }) }
// Lever le cadrage par le besoin change le PÉRIMÈTRE : le lot ouvert peut ne
// plus en faire partie. Comme le rang et la marge, on le relâche. Et le défaut
// ne s'écrit pas dans l'URL — seule la LEVÉE s'y voit (`?need=0`), ce qui garde
// les liens courts et rend le réglage non-défaut visible d'un coup d'œil.
function setNeedOnly(on: boolean) {
  patch({ need: on ? undefined : '0', lot: undefined })
}
function setCountryOnly(on: boolean) {
  // Comme le rang et la marge : changer le périmètre relâche le lot ouvert,
  // qui peut ne plus en faire partie.
  patch({ pays: on ? undefined : 'tous', lot: undefined })
}

// La query que lisent les vues de review (SingleReviewView lit `dino_class`,
// `dino_rank`, `tri` et `dino_min` directement dans l'URL).
watch([classId, rank, minSpread, countryOnly], () => {
  if (!classId.value) return
  const q: Record<string, unknown> = { ...route.query, tri: 'dino' }
  q.dino_class = classId.value
  q.dino_rank = String(rank.value)
  if (countryOnly.value) delete q.dino_country_only
  else q.dino_country_only = 'false'
  if (minSpread.value == null) delete q.dino_min
  else q.dino_min = String(minSpread.value)
  void router.replace({ query: q as Record<string, string> })
}, { immediate: true })

// ── Périmètre côté lots ───────────────────────────────────────────────────
const lotScope = computed<Record<string, string>>(() => {
  const out: Record<string, string> = {}
  if (!classId.value) return out
  out.dino_class = classId.value
  out.dino_rank = String(rank.value)
  if (minSpread.value != null) out.dino_min_spread = String(minSpread.value)
  if (!countryOnly.value) out.dino_country_only = 'false'
  // Sans ça, le mode LOT de la pêche resterait le seul endroit non cadré par
  // le besoin — et c'est là que vivent la plupart des crops (60 sur 66 pour
  // `lu-2002-…henri-i`). Un périmètre à moitié appliqué est pire qu'aucun :
  // les deux modes d'un même écran ne serviraient pas la même population.
  if (needOnly.value) out.need_only = 'true'
  return out
})
const {
  heldLot, loading: lotLoading, exhausted: lotExhausted,
  goto: gotoLot, finish: lotsFinished,
} = useLotChain(lotScope, () => mode.value === 'lot' && !!classId.value)

// ── Ce que la banque propose, et ce qui est hors file ─────────────────────
const summary = ref<DinoCandidatesSummary | null>(null)
const loading = ref(false)
async function loadSummary() {
  if (!classId.value) { summary.value = null; return }
  loading.value = true
  try {
    summary.value = await fetchDinoCandidates(classId.value, {
      rank: rank.value, minSpread: minSpread.value,
      countryOnly: countryOnly.value,
      // Le bandeau doit compter CE QUE LA FILE SERT. Compter le pool brut
      // au-dessus d'une file cadrée, c'est le badge qui annonce 4 sur une
      // file qui en sert 3 — et sur une classe pleine il annoncerait 257
      // au-dessus de zéro.
      needOnly: needOnly.value,
    })
  } finally {
    loading.value = false
  }
}
watch([classId, rank, minSpread, countryOnly, needOnly], loadSummary, { immediate: true })

// Le mode par défaut suit le stock. Sans ça, une classe dont les singles sont
// épuisés ouvre sur « Tout est résolu » alors que quatre-vingts crops de lots
// l'attendent — un écran vide et faux, exactement ce qu'on cherche à ne plus
// produire. On ne bouscule PAS un choix explicite : la bascule ne joue que
// tant que `?mode=` est absent de l'URL.
watch(summary, (s) => {
  if (!s || modeChosen.value) return
  if (mode.value === 'single' && s.n_open_single === 0 && s.n_open_lot > 0) {
    patch({ mode: 'lot' })
  }
})

// Enfiler les orphelins — une ÉCRITURE, donc jamais au fil d'une lecture.
// Elle part au canonique (writer unique), comme la décision de review.
const enqueuing = ref(false)
const enqueueMsg = ref<string | null>(null)
async function enqueueOrphans() {
  const ids = summary.value?.orphan_asset_ids ?? []
  if (!ids.length || enqueuing.value) return
  enqueuing.value = true
  enqueueMsg.value = null
  try {
    const res = await reflagAssetsNeedsReview(ids)
    enqueueMsg.value = `${res.n_reflagged} crop(s) enfilé(s)`
      + (res.n_skipped ? ` · ${res.n_skipped} ignoré(s)` : '')
    await loadSummary()
  } catch (err) {
    enqueueMsg.value = `Échec : ${err instanceof Error ? err.message : String(err)}`
  } finally {
    enqueuing.value = false
  }
}

/** Saisie manuelle d'une classe — l'entrée normale reste la page d'une pièce. */
const draft = ref('')
watch(classId, (v) => { draft.value = v }, { immediate: true })
function applyDraft() {
  const v = draft.value.trim()
  patch({ class: v || undefined, lot: undefined })
}

const nothingHere = computed(
  () => summary.value !== null
    && summary.value.n_open_single === 0
    && summary.value.n_open_lot === 0,
)
</script>

<template>
  <div class="flex h-full flex-col">
    <header
      class="flex flex-wrap items-center justify-between gap-4 border-b px-8 py-3"
      style="border-color: var(--surface-3); background: var(--surface);"
    >
      <div class="flex items-center gap-4">
        <button
          type="button" class="linkish"
          @click="router.push(canArbitrate ? '/review' : '/')"
        >
          <ArrowLeft class="inline h-3 w-3" />
          {{ canArbitrate ? 'Review queue' : 'Accueil' }}
        </button>
        <h1 class="font-display text-2xl italic font-semibold" style="color: var(--indigo-700);">
          Pêche
        </h1>
        <p class="hidden max-w-[52ch] text-[11.5px] md:block" style="color: var(--ink-500);">
          La file par <b>ce que le modèle reconnaît</b>, pas par ce que le scrape
          visait — lots compris.
        </p>
      </div>
      <form class="flex items-center gap-2" @submit.prevent="applyDraft">
        <input
          v-model="draft"
          class="cls-input"
          placeholder="design_group_id ou eurio_id"
          aria-label="Classe à pêcher"
        />
        <button type="submit" class="btn">Pêcher</button>
      </form>
    </header>

    <PecheBar
      v-if="classId"
      :class-id="classId"
      :rank="rank"
      :min-spread="minSpread"
      :mode="mode"
      :country-only="countryOnly"
      :summary="summary"
      :loading="loading"
      :enqueuing="enqueuing"
      @rank="setRank"
      @min-spread="setMinSpread"
      @mode="setMode"
      @country-only="setCountryOnly"
      @enqueue-orphans="enqueueOrphans"
      @need-only="setNeedOnly"
    />
    <p v-if="enqueueMsg" class="msg msg--info">{{ enqueueMsg }}</p>

    <div v-if="!classId" class="msg">
      <b>Aucune classe.</b> On entre normalement ici depuis la page d'une pièce
      (« DINO a repéré N crops pour cette classe »), ou depuis une cohorte. Tu
      peux aussi coller un identifiant de classe ci-dessus — un
      <code>design_group_id</code> pour une pièce courante
      (<code>it-2euro-standard-t1</code>), son <code>eurio_id</code> pour une
      commémorative.
    </div>

    <div v-else-if="nothingHere && (summary?.n_parked ?? 0) > 0" class="msg">
      <b>Cette classe est pleine — {{ summary?.class_have }}/{{ summary?.class_target }} en banque.</b>
      Ses <b>{{ summary?.n_parked }} crops ouverts sont parqués</b> : on ne les
      sert plus (D2), mais ils ne sont <b>ni fermés ni supprimés</b> — ils
      restent en base, retrouvables, et serviront la voie A.
      <button type="button" class="linkish" @click="setNeedOnly(false)">
        Les revoir quand même
      </button>
      — ou retourne au <RouterLink class="linkish" to="/besoin">besoin</RouterLink>
      pour une classe qui en a encore.
    </div>

    <div v-else-if="nothingHere" class="msg">
      <b>Rien à pêcher pour cette classe</b> au rang {{ rank }}<span v-if="minSpread"> et à la marge ≥ {{ minSpread }}</span>.
      Élargis le filet (Top 3, Top 5, marge « toutes »<span v-if="countryOnly">,
      ou lève le filtre pays</span>), ou la classe manque simplement de
      matière — c'est alors un sujet de scrape, pas de tri.
    </div>

    <div v-else class="flex-1 overflow-hidden">
      <SingleReviewView v-if="mode === 'single'" :key="`s-${classId}-${rank}-${minSpread}`" />
      <LotDetailView
        v-else-if="heldLot"
        :key="`l-${heldLot}`"
        :listing-key="heldLot"
        :scope="lotScope"
        @navigate="gotoLot"
        @exhausted="lotsFinished"
      />
      <p v-else-if="lotLoading" class="msg">Ouverture du premier lot…</p>
      <p v-else-if="lotExhausted" class="msg">
        <b>Plus de lot à trancher</b> dans ce périmètre.
        <button type="button" class="linkish" @click="setMode('single')">
          Passer à l'unité
        </button>
      </p>
    </div>
  </div>
</template>

<style scoped>
.cls-input {
  font-family: var(--font-mono);
  font-size: 11.5px;
  padding: 6px 10px;
  min-width: 27ch;
  border-radius: 7px;
  border: 1px solid var(--surface-3);
  background: var(--surface-1);
  color: var(--ink);
}
.cls-input:focus-visible { outline: 2px solid var(--gold); outline-offset: 1px; }
.btn {
  font-size: 12.5px;
  padding: 6px 14px;
  border-radius: 7px;
  border: 1px solid var(--indigo-700);
  background: var(--indigo-700);
  color: var(--surface);
  cursor: pointer;
}
.msg {
  padding: 26px 32px;
  font-size: 13.5px;
  color: var(--ink-500);
  max-width: 78ch;
  line-height: 1.6;
}
.msg b { color: var(--ink); font-weight: 600; }
.msg code {
  font-family: var(--font-mono);
  font-size: 11.5px;
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--surface-2);
}
.msg--info { padding: 8px 32px; color: var(--indigo-700); font-family: var(--font-mono); font-size: 11px; }
.linkish {
  font-size: 12px;
  color: var(--indigo-700);
  text-decoration: underline;
  text-underline-offset: 2px;
  cursor: pointer;
  background: none;
  border: none;
  padding: 0;
}
</style>
