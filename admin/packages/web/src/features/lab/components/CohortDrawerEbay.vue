<script setup lang="ts">
// Tiroir §C3 — eBay : sourcing & funnel (fusion des anciens §C3 + §C3b).
// Une seule table par coin qui suit tout le tunnel eBay : scrape → crop →
// routing → review → training-eligible → sources réelles. Rows multi-lignes
// (row-card) : identité + sourcing, funnel lu comme une phrase, actions.
// Chaque coin deep-linke vers le studio bench filtré sur la pièce
// (`/bench/runs/<run>?eurio_id=<coin>`). On NE réimplémente PAS le bench.

import DrawerSection from '@/features/lab/components/DrawerSection.vue'
import {
  useCohortDedupStatusQuery,
  useCohortFunnelStatusQuery,
  useCohortJobsQuery,
  useDiscardSummaryQuery,
  useEbayRunningRunsQuery,
  useRecropZeroCoinMutation,
  useTriggerCoinEbayScrapeMutation,
  useTriggerCohortEbayScrapeMutation,
} from '@/features/lab/composables/useLabQueries'
import type { CohortFunnelCoin, CohortJob, CohortSummary, DrawerState, EbayRunLive, RescuedToSister } from '@/features/lab/types'
import { ArrowUpRight, Crop as CropIcon, Filter, Loader2, Package, RefreshCw, Search } from 'lucide-vue-next'
import { computed, ref } from 'vue'

const props = defineProps<{
  cohortId: string
  cohort: CohortSummary
}>()

const statusQuery = useCohortFunnelStatusQuery(() => props.cohortId)
const discardQuery = useDiscardSummaryQuery(() => props.cohortId)
const scrape = useTriggerCohortEbayScrapeMutation(() => props.cohortId)
const coinScrape = useTriggerCoinEbayScrapeMutation(() => props.cohortId)
const recrop = useRecropZeroCoinMutation(() => props.cohortId)

const status = computed(() => statusQuery.data.value ?? null)
const loading = computed(() => statusQuery.isPending.value)
const dedupQuery = useCohortDedupStatusQuery(() => props.cohortId)
const dedup = computed(() => dedupQuery.data.value ?? null)
const discardSummary = computed(() => discardQuery.data.value ?? null)
const perCoin = computed<CohortFunnelCoin[]>(() => status.value?.per_coin ?? [])
const groups = computed(() => status.value?.head.groups ?? [])
const rescuedToSisters = computed<RescuedToSister[]>(() => status.value?.rescued_to_sisters ?? [])
const rescuedTotal = computed(() => rescuedToSisters.value.reduce((a, r) => a + r.n, 0))
const minReal = computed(() => status.value?.min_real_sources ?? 10)
const trainingTarget = computed(() => status.value?.training_target ?? 100)
const quota = computed(() => status.value?.quota ?? null)
const nonScrapable = computed(() => status.value?.non_scrapable ?? [])

const totals = computed(() => {
  const pc = perCoin.value
  const sum = (f: (c: CohortFunnelCoin) => number) => pc.reduce((a, c) => a + f(c), 0)
  return {
    listings: sum(c => c.n_source_images),
    downloaded: sum(c => c.n_downloaded),
    crops: sum(c => c.n_crops),
    // File de review VIVANTE (image_state_current), pas le route_decision gelé.
    review: sum(c => c.n_in_review),
    resolved: sum(c => c.n_resolved_training),
    // « non routés » = listings pas encore téléchargés/routés (route_decision=
    // 'pending') — PAS une file de review. Renommé pour lever l'ambiguïté.
    unrouted: sum(c => c.n_pending),
    orphaned: sum(c => c.n_orphaned),
    rejected: sum(c => c.n_rejected),
  }
})
// Pièces sous le plancher de sources RÉELLES (diversité faible) → à enrichir.
const flaggedCount = computed(
  () => perCoin.value.filter(c => c.below_real_floor ?? !c.enough).length,
)

// Compteurs d'action par pièce (recrop = raws sans crop ; review = crops à trancher).
function recropCount(c: CohortFunnelCoin): number {
  return c.n_zero_crops ?? 0
}
// File RÉELLEMENT ouverte (review_queue), pas le route_decision figé : c'est ce
// qui reste à trancher. Singles scopables par pièce ; lots = flow cohorte.
function reviewCount(c: CohortFunnelCoin): number {
  return c.n_open_review_single ?? 0
}
function lotReviewCount(c: CohortFunnelCoin): number {
  return c.n_open_review_lot ?? 0
}

// ── Jobs recrop observables (F5 / B2) — lus depuis cohort_jobs, pas de thread
// mémoire. Dernier job recrop_zero par pièce → barre de progression si running,
// note « tenté/épuisé » si done à 0 crop (fin du bouton zombie).
const jobsQuery = useCohortJobsQuery(() => props.cohortId)
const recropJobByCoin = computed<Record<string, CohortJob>>(() => {
  const m: Record<string, CohortJob> = {}
  for (const j of jobsQuery.data.value ?? []) {
    if (j.kind !== 'recrop_zero' || !j.eurio_id) continue
    const prev = m[j.eurio_id]
    if (!prev || j.started_at > prev.started_at) m[j.eurio_id] = j
  }
  return m
})
function recropJob(c: CohortFunnelCoin): CohortJob | null {
  return recropJobByCoin.value[c.eurio_id] ?? null
}
function recropRunning(c: CohortFunnelCoin): boolean {
  return recropJob(c)?.status === 'running' || recroppingCoin.value === c.eurio_id
}
// Épuisé = dernier recrop terminé sans produire de crop → re-proposer « Recropper »
// serait un bouton zombie. On grise + on affiche la note du job.
function recropExhausted(c: CohortFunnelCoin): boolean {
  const j = recropJob(c)
  return j != null && j.status === 'done' && j.n_produced === 0
}
function recropProgressPct(c: CohortFunnelCoin): number {
  const j = recropJob(c)
  if (!j || !j.n_total) return 0
  return Math.min(100, Math.round((j.n_done / j.n_total) * 100))
}
// Grammaire d'actions (F2) : UNE seule action PRIMAIRE par pièce selon l'état,
// arbre de priorité strict (review singles > review lots > recrop > scrape).
// Les autres actions applicables passent en secondaire (subordonné visuellement).
// → toujours 0 ou 1 bouton plein par row : règle le grief « les boutons se mélangent ».
function primaryAction(c: CohortFunnelCoin): 'review' | 'lot' | 'recrop' | 'scrape' | null {
  if (reviewCount(c) > 0) return 'review'
  if (lotReviewCount(c) > 0) return 'lot'
  if (recropCount(c) > 0 && !recropExhausted(c)) return 'recrop'
  if (c.scrapable && (c.below_real_floor ?? !c.enough)) return 'scrape'
  return null
}
// Jauge santé = sources réelles eBay vs plancher (≥ plancher = vert).
function realBarPct(c: CohortFunnelCoin): number {
  return Math.min(100, Math.round((c.n_training_eligible / Math.max(minReal.value, 1)) * 100))
}

const state = computed<DrawerState>(() => {
  if (scrape.isPending.value) return 'running'
  if (loading.value || !status.value) return 'empty'
  if (totals.value.listings === 0) return 'empty'
  return (totals.value.review > 0 || totals.value.unrouted > 0) ? 'partial' : 'ready'
})

const summary = computed(() => {
  if (loading.value || !status.value) return 'Chargement…'
  const t = totals.value
  if (t.listings === 0) return 'Aucun listing scrapé pour cette cohort'
  const flag = flaggedCount.value > 0 ? ` · ${flaggedCount.value} sous plancher réel` : ''
  const non = nonScrapable.value.length > 0 ? ` · ${nonScrapable.value.length} hors eBay` : ''
  return `${fmt(t.listings)} → ${fmt(t.crops)} crops → ${fmt(t.review)} en review${flag}${non}`
})

function fmt(n: number): string {
  return n.toLocaleString('fr-FR')
}
function groupLabel(g: { country: string | null; year: number | null }): string {
  const y = g.year != null ? String(g.year) : 'toutes années'
  return `${g.country ?? '?'} · ${y}`
}

// Deep-link vers le studio bench, pré-filtré sur la pièce (run le plus récent).
function benchLink(c: CohortFunnelCoin, hash: '#filter' | '#crop') {
  return { path: `/bench/runs/${c.latest_run_id}`, query: { eurio_id: c.eurio_id }, hash }
}

// ── Scrape cohort (consomme le quota eBay — confirmation) ──────────────────
const quotaInsufficient = computed(() => quota.value?.ok === false)
const scrapeDisabled = computed(() => scrape.isPending.value || quotaInsufficient.value)
const triggered = ref<string | null>(null)

async function onScrape() {
  const est = quota.value?.estimate ?? '?'
  const ok = window.confirm(
    `Lancer un scrape eBay scopé à « ${props.cohort.name} » ?\n\n`
    + `Estimation ~${est} appels Browse API (consomme ton quota eBay).\n`
    + `Le run tourne en arrière-plan ; reviens reviewer dans /review.`,
  )
  if (!ok) return
  triggered.value = null
  const res = await scrape.mutateAsync()
  triggered.value = res.run_id
}

// ── Badge run live (polling 3s) ────────────────────────────────────────────
const runningRunsQuery = useEbayRunningRunsQuery()
const runningRuns = computed<EbayRunLive[]>(() => runningRunsQuery.data.value ?? [])
const liveRun = computed<EbayRunLive | null>(() => runningRuns.value[0] ?? null)

// Rescrape ciblé par pièce. On suit la pièce en cours + le run lancé.
const scrapingCoin = ref<string | null>(null)
const coinTriggered = ref<Record<string, string>>({})

async function onRescrape(c: CohortFunnelCoin) {
  const ok = window.confirm(
    `Rescrape eBay ciblé sur « ${c.eurio_id} » ?\n\n`
    + `Consomme ton quota eBay (résolu vers son groupe de découverte). `
    + `Le run tourne en arrière-plan ; reviens reviewer dans /review.`,
  )
  if (!ok) return
  scrapingCoin.value = c.eurio_id
  try {
    const res = await coinScrape.mutateAsync(c.eurio_id)
    coinTriggered.value = { ...coinTriggered.value, [c.eurio_id]: res.run_id }
  } catch (e) {
    alert(`Rescrape échoué : ${(e as Error).message}`)
  } finally {
    scrapingCoin.value = null
  }
}

// Recrop des raws zéro-crop d'une pièce (census+gate). Local, sans quota eBay.
const recroppingCoin = ref<string | null>(null)
const recropTriggered = ref<Record<string, string>>({})

async function onRecrop(c: CohortFunnelCoin) {
  const n = recropCount(c)
  const ok = window.confirm(
    `Recropper les ${n} raws sans crop de « ${c.eurio_id} » ?\n\n`
    + `Re-détection census + gate anti-fragment sur les images déjà téléchargées `
    + `(ne consomme PAS le quota eBay). Les crops récupérés partent en review.\n`
    + `Le job tourne en arrière-plan ; les crops apparaîtront au fil de l'eau.`,
  )
  if (!ok) return
  recroppingCoin.value = c.eurio_id
  try {
    const res = await recrop.mutateAsync(c.eurio_id)
    recropTriggered.value = { ...recropTriggered.value, [c.eurio_id]: res.run_id }
  } catch (e) {
    alert(`Recrop échoué : ${(e as Error).message}`)
  } finally {
    recroppingCoin.value = null
  }
}
</script>

<template>
  <DrawerSection
    number="C3"
    title="eBay — sourcing & funnel"
    :state="state"
    :summary="summary"
  >
    <template #body>
      <div v-if="loading" class="text-xs" style="color: var(--ink-400);">
        Chargement du statut eBay…
      </div>
      <template v-else-if="status">
        <!-- Ruban funnel cohort + action scrape -->
        <div class="ribbon">
          <div class="ribbon__cell">
            <span class="ribbon__n">{{ fmt(totals.listings) }}</span>
            <span class="ribbon__lbl">listings retenus</span>
          </div>
          <span class="ribbon__arr">→</span>
          <div class="ribbon__cell">
            <span class="ribbon__n">{{ fmt(totals.downloaded) }}</span>
            <span class="ribbon__lbl">téléchargés</span>
          </div>
          <span class="ribbon__arr">→</span>
          <div class="ribbon__cell">
            <span class="ribbon__n">{{ fmt(totals.crops) }}</span>
            <span class="ribbon__lbl">crops</span>
          </div>
          <span class="ribbon__arr">→</span>
          <div class="ribbon__cell ribbon__cell--accent">
            <span class="ribbon__n">{{ fmt(totals.review) }}</span>
            <span class="ribbon__lbl">en review</span>
          </div>
          <div class="ribbon__aside">
            <span style="color: var(--success);"><b>{{ fmt(totals.resolved) }}</b> validés (train)</span>
            <span><b>{{ fmt(totals.unrouted) }}</b> non routés</span>
            <span v-if="totals.orphaned" style="color: var(--warning);"><b>{{ totals.orphaned }}</b> jamais croppés</span>
            <span v-if="totals.rejected"><b>{{ totals.rejected }}</b> rejetés</span>
          </div>
        </div>

        <!-- Rescue cross-classe : travail validé parti vers des pièces sœurs
             hors cohort (visible pour ne pas paraître perdu — pas compté dans
             les cibles de la cohort) -->
        <details v-if="rescuedTotal > 0" class="mt-2 sisters">
          <summary class="sisters__summary">
            {{ rescuedTotal }} crops validés rescués → {{ rescuedToSisters.length }} pièces sœurs (hors cohort)
          </summary>
          <ul class="sisters__list">
            <li v-for="r in rescuedToSisters" :key="`${r.source_coin}-${r.sister_eurio_id}`">
              <span class="sisters__src">{{ r.source_coin }}</span>
              <span class="sisters__arr">→</span>
              <span class="sisters__dst">{{ r.sister_eurio_id }}</span>
              <span class="sisters__n">{{ r.n }}</span>
            </li>
          </ul>
          <p class="sisters__note">
            Crops scrapés sous un groupe de la cohort mais ré-attribués en review à
            leur vraie pièce (sœur du même groupe). Training valide pour la sœur ;
            non comptés dans le seed des pièces de la cohort.
          </p>
        </details>

        <!-- Badge run live (visible uniquement si un run eBay tourne) -->
        <div v-if="liveRun" class="live-badge">
          <Loader2 class="h-3 w-3 animate-spin" />
          run {{ liveRun.id.slice(0, 8) }} · {{ liveRun.current_step ?? 'init' }}
          <span class="font-mono">+{{ liveRun.n_raws_added }} raws · +{{ liveRun.n_crops_added }} crops</span>
        </div>

        <!-- Barre d'action scrape cohort -->
        <div class="mt-3 flex flex-wrap items-center gap-3">
          <button
            type="button"
            class="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium"
            :disabled="scrapeDisabled"
            :style="{
              background: quotaInsufficient ? 'var(--surface-2)' : 'var(--indigo-700)',
              color: quotaInsufficient ? 'var(--ink-400)' : 'white',
              cursor: scrapeDisabled ? 'not-allowed' : 'pointer',
            }"
            @click="onScrape"
          >
            <Loader2 v-if="scrape.isPending.value" class="h-3.5 w-3.5 animate-spin" />
            <Search v-else class="h-3.5 w-3.5" />
            Lancer scrape eBay (cohort)
          </button>
          <span v-if="quota" class="text-[11px]" style="color: var(--ink-500);">
            ~{{ quota.estimate }} appels · {{ quota.remaining }}/{{ quota.limit }} restants
            <span v-if="quotaInsufficient" style="color: var(--danger);">· quota insuffisant</span>
          </span>
          <span
            v-if="triggered"
            class="rounded px-2 py-0.5 text-[10px] font-mono"
            style="background: color-mix(in srgb, var(--success) 12%, var(--surface)); color: var(--success);"
          >
            run {{ triggered.slice(0, 8) }} lancé →
            <RouterLink to="/review" style="text-decoration: underline;">review</RouterLink>
          </span>
          <RouterLink
            :to="{ path: '/crop-bench', query: { cohort: cohortId } }"
            class="coin__audit"
            title="Banc de qualité crop eBay — scopé sur cette cohorte"
          >
            <CropIcon class="h-3.5 w-3.5" /> Voir qualité crops
          </RouterLink>
        </div>

        <!-- F4 : ligne-exemple annotée (légende ouverte par défaut) — explique
             chaque chiffre et chaque action une fois pour toutes. -->
        <details open class="mt-3 legend">
          <summary class="legend__summary">Comment lire une ligne (légende)</summary>
          <div class="legend__example">
            <div class="coin__l1">
              <span class="coin__id">xx-2099-2eur-exemple</span>
              <span class="coin__sources">
                <span class="coin__proj">
                  <span class="coin__proj-bar"><span class="coin__proj-fill" style="width: 100%; background: var(--success);" /></span>
                  <b style="color: var(--success);">110</b><span style="color: var(--ink-400);">img</span>
                  <span class="coin__proj-detail">11 réels ×10</span>
                </span>
              </span>
            </div>
            <div class="coin__funnel">
              <b>185</b> listings <span class="coin__arr">→</span>
              <b>160</b> téléchargés <span class="coin__arr">→</span>
              <b>120</b> crops <span class="coin__arr">→</span>
              <b style="color: var(--indigo-700);">38</b> en review
              <span class="coin__dot">·</span><span style="color: var(--success);">11 validés</span>
              <span class="coin__dot">·</span><span style="color: var(--ink-500);">3 rejetés</span>
            </div>
            <div class="coin__actions">
              <span class="coin__btn coin__btn--primary"><Search class="h-3 w-3" /> Reviewer 38</span>
              <span class="coin__btn coin__btn--scrape"><RefreshCw class="h-3 w-3" /> Rescraper</span>
            </div>
          </div>
          <dl class="legend__key">
            <dt><b>110 img</b> · jauge</dt><dd>images projetées (réels × facteur d'aug) vs cible ≥{{ trainingTarget }}. Jauge <span style="color: var(--success);">verte</span> = assez de réels (plancher {{ minReal }}), <span style="color: var(--warning);">orange</span> = à enrichir.</dd>
            <dt>listings</dt><dd>annonces eBay attribuées à cette pièce</dd>
            <dt>téléchargés</dt><dd>images rapatriées (download OK) — <em>avant</em> le crop</dd>
            <dt>crops</dt><dd>crops produits par l'autocrop (≠ « Recropper »)</dd>
            <dt style="color: var(--indigo-700);">en review</dt><dd>crops qui attendent une décision — file <b>vivante</b> (= le bouton « Reviewer N »)</dd>
            <dt style="color: var(--success);">validés</dt><dd>tranchés ET éligibles training</dd>
            <dt style="color: var(--warning);">jamais croppés</dt><dd>raws téléchargés sans aucun crop → « Recropper »</dd>
            <dt>non routés</dt><dd>listings pas encore téléchargés/routés (ni review ni crop)</dd>
            <dt>action <span class="legend__chip legend__chip--primary">pleine</span></dt><dd>LA chose à faire maintenant (1 seule par ligne) — Reviewer &gt; Recropper &gt; Scraper</dd>
            <dt>action <span class="legend__chip">discrète</span></dt><dd>secondaire ; <b>Rescraper</b> consomme le quota eBay</dd>
          </dl>
        </details>

        <!-- Liste de row-cards par coin -->
        <div class="mt-3 overflow-hidden rounded-md border" style="border-color: var(--surface-3);">
          <div
            v-for="c in perCoin"
            :key="c.eurio_id"
            class="coin"
          >
            <!-- L1 : identité + sourcing -->
            <div class="coin__l1">
              <span class="coin__id">
                <span
                  v-if="c.never_scraped && c.group_scraped"
                  class="coin__badge coin__badge--warn"
                  title="Groupe scrapé, mais 0 listing attribué à cette pièce — eBay n'a rien renvoyé pour ce millésime (dispersé sur ses sœurs). Récupère via la review des lots du groupe."
                >0 attribué</span>
                <span
                  v-else-if="c.never_scraped"
                  class="coin__badge coin__badge--danger"
                  title="Jamais scrapé — le groupe de découverte de cette pièce n'a pas encore été cherché sur eBay"
                >jamais scrapé</span>
                <span
                  v-if="!c.scrapable"
                  class="coin__badge"
                  title="hors découverte groupée eBay — Numista-only"
                >Numista-only</span>
                {{ c.eurio_id }}
              </span>
              <span class="coin__sources">
                <span
                  class="coin__proj"
                  :title="`${c.n_seed} sources réelles (${c.n_training_eligible} eBay + ${c.n_numista_ref} Numista + ${c.n_bce_ref} réf) × ${c.aug_factor} augmentation = ${c.n_projected} images projetées (cible ≥ ${trainingTarget}). Jauge = sources eBay réelles vs plancher ${minReal}.`"
                >
                  <span class="coin__proj-bar">
                    <span
                      class="coin__proj-fill"
                      :style="{
                        width: realBarPct(c) + '%',
                        background: c.below_real_floor ? 'var(--warning)' : 'var(--success)',
                      }"
                    />
                  </span>
                  <b :style="{ color: c.below_real_floor ? 'var(--warning)' : 'var(--success)' }">{{ c.n_projected }}</b>
                  <span style="color: var(--ink-400);">img</span>
                  <span class="coin__proj-detail">{{ c.n_seed }} réels ×{{ c.aug_factor }}</span>
                </span>
              </span>
            </div>

            <!-- L2 : funnel (phrase) -->
            <div class="coin__funnel">
              <template v-if="c.n_source_images > 0">
                <b>{{ c.n_source_images }}</b> listings
                <span class="coin__arr">→</span>
                <b>{{ c.n_downloaded }}</b> téléchargés
                <template v-if="c.n_download_failed > 0">
                  <span class="coin__dot">·</span>
                  <span style="color: var(--danger);">{{ c.n_download_failed }} ✗</span>
                </template>
                <span class="coin__arr">→</span>
                <b>{{ c.n_crops }}</b> crops
                <span class="coin__arr">→</span>
                <b style="color: var(--indigo-700);">{{ c.n_in_review }}</b> en review
                <template v-if="c.n_resolved_training > 0">
                  <span class="coin__dot">·</span>
                  <span style="color: var(--success);">{{ c.n_resolved_training }} validés</span>
                </template>
                <template v-if="(c.state_counts?.rejected ?? 0) > 0">
                  <span class="coin__dot">·</span>
                  <span style="color: var(--ink-500);">{{ c.state_counts.rejected }} rejetés</span>
                </template>
                <template v-if="c.n_orphaned > 0">
                  <span class="coin__dot">·</span>
                  <span style="color: var(--warning);">{{ c.n_orphaned }} jamais croppés</span>
                </template>
                <template v-if="c.n_pending > 0">
                  <span class="coin__dot">·</span>
                  <span style="color: var(--ink-400);">{{ c.n_pending }} non routés</span>
                </template>
              </template>
              <span v-else style="color: var(--ink-400);">aucun listing scrapé</span>
            </div>

            <!-- L3 : actions diagnostiquées selon la vraie cause (§WS4) -->
            <div class="coin__actions">
              <!-- 1. Crops déjà là à trancher → reviewer (transforme en train) -->
              <RouterLink
                v-if="reviewCount(c) > 0"
                :to="{ path: '/review/manual', query: { cohort: cohortId, eurio_id: c.eurio_id } }"
                :class="['coin__btn', { 'coin__btn--primary': primaryAction(c) === 'review' }]"
                :title="`${reviewCount(c)} crops en review POUR ${c.eurio_id} — review scopée à cette pièce, trancher fait monter sa ligne`"
              >
                <Search class="h-3 w-3" /> Reviewer {{ reviewCount(c) }}
              </RouterLink>

              <!-- 1b. Reste en review LOT (flow cohorte, multi-pièces) -->
              <RouterLink
                v-if="lotReviewCount(c) > 0"
                :to="{ path: '/review/manual', query: { cohort: cohortId, mode: 'lot' } }"
                :class="['coin__btn', { 'coin__btn--primary': primaryAction(c) === 'lot' }]"
                :title="`${lotReviewCount(c)} crops en review LOT touchant ${c.eurio_id} — flow cohorte multi-pièces`"
              >
                <Package class="h-3 w-3" /> {{ lotReviewCount(c) }} lots
              </RouterLink>

              <!-- 2. Raws téléchargés sans crop → recropper (local, sans quota).
                   F5/B2 : 3 états lus depuis cohort_jobs (observable, persisté). -->
              <!-- 2a. recrop en cours → barre de progression in-row (n_done/n_total) -->
              <span
                v-if="recropRunning(c)"
                class="coin__job"
                :title="`Recrop en cours — ${recropJob(c)?.n_done ?? 0}/${recropJob(c)?.n_total ?? recropCount(c)} raws`"
              >
                <Loader2 class="h-3 w-3 animate-spin" />
                <span class="coin__job-bar">
                  <span class="coin__job-fill" :style="{ width: recropProgressPct(c) + '%' }" />
                </span>
                <span class="coin__job-lbl">recrop {{ recropJob(c)?.n_done ?? 0 }}/{{ recropJob(c)?.n_total ?? recropCount(c) }}</span>
              </span>
              <!-- 2b. recrop épuisé (dernier job done à 0 crop) → grisé, plus de zombie -->
              <span
                v-else-if="recropCount(c) > 0 && recropExhausted(c)"
                class="coin__btn coin__btn--exhausted"
                :title="recropJob(c)?.note ?? 'Recrop tenté, 0 crop récupérable au seuil courant'"
              >
                <CropIcon class="h-3 w-3" /> recrop tenté (0)
              </span>
              <!-- 2c. recrop disponible -->
              <button
                v-else-if="recropCount(c) > 0"
                type="button"
                :class="['coin__btn', { 'coin__btn--primary': primaryAction(c) === 'recrop' }]"
                :disabled="recroppingCoin !== null"
                :style="{ opacity: recroppingCoin !== null ? 0.5 : 1, cursor: recroppingCoin !== null ? 'not-allowed' : 'pointer' }"
                :title="`Recropper ${recropCount(c)} raws sans crop (census+gate, sans quota eBay)`"
                @click="onRecrop(c)"
              >
                <CropIcon class="h-3 w-3" />
                <span>Recropper {{ recropCount(c) }}</span>
              </button>

              <!-- 3. Scrape eBay : jamais scrapé → Scraper ; sinon Rescraper (nouvelles annonces) -->
              <button
                v-if="c.scrapable"
                type="button"
                :class="['coin__btn', primaryAction(c) === 'scrape' ? 'coin__btn--primary' : 'coin__btn--scrape']"
                :disabled="scrapingCoin !== null"
                :style="{ opacity: scrapingCoin !== null ? 0.5 : 1, cursor: scrapingCoin !== null ? 'not-allowed' : 'pointer' }"
                :title="c.never_scraped
                  ? `Scraper eBay pour ${c.eurio_id} (jamais scrapé)`
                  : `Rescraper eBay (nouvelles annonces) — consomme le quota`"
                @click="onRescrape(c)"
              >
                <Loader2 v-if="scrapingCoin === c.eurio_id" class="h-3 w-3 animate-spin" />
                <RefreshCw v-else class="h-3 w-3" />
                <span v-if="coinTriggered[c.eurio_id]" class="font-mono">{{ coinTriggered[c.eurio_id].slice(0, 6) }}</span>
                <span v-else>{{ c.never_scraped ? 'Scraper' : 'Rescraper' }}</span>
              </button>
              <span v-else class="coin__muted">hors découverte eBay</span>
              <span
                v-if="!c.below_real_floor && reviewCount(c) === 0 && recropCount(c) === 0"
                class="coin__muted"
                style="color: var(--success);"
              >assez de réels</span>

              <template v-if="c.latest_run_id">
                <RouterLink
                  :to="benchLink(c, '#filter')"
                  class="coin__audit"
                  :title="`Audit filtres theme-matcher${c.n_runs > 1 ? ' — vu sur ' + c.n_runs + ' runs, lien vers le dernier' : ''}`"
                >
                  <Filter class="h-3 w-3" /> filtres <ArrowUpRight class="h-2.5 w-2.5" />
                </RouterLink>
                <RouterLink :to="benchLink(c, '#crop')" class="coin__audit coin__audit--muted" title="Audit crops (forensics)">
                  <CropIcon class="h-3 w-3" /> crops
                </RouterLink>
              </template>
              <span v-else-if="c.scrapable" class="coin__muted">pas encore scrapé</span>
            </div>
          </div>
        </div>

        <!-- Bloc Découverte (head pré-attribution, maille recherche) -->
        <details class="mt-3 head">
          <summary class="head__summary">
            Découverte — {{ groups.length }} recherches (annonces brutes → retenues, pré-attribution)
          </summary>
          <div class="mt-2 overflow-hidden rounded-md border" style="border-color: var(--surface-3);">
            <table class="w-full text-xs">
              <thead>
                <tr style="background: var(--surface-1); color: var(--ink-500);">
                  <th class="px-3 py-1.5 text-left font-medium">recherche</th>
                  <th class="px-2 py-1.5 text-right font-medium" title="recherches Browse (× marketplaces/langues)">srch</th>
                  <th class="px-2 py-1.5 text-right font-medium" title="N0 — itemSummaries bruts">brut</th>
                  <th class="px-2 py-1.5 text-right font-medium" title="N3 — retenus après accept_listing">retenus</th>
                  <th class="px-2 py-1.5 text-left font-medium" title="rejets attribuables au groupe (par raison)">jetés (raisons)</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="g in groups"
                  :key="`${g.country}-${g.year}-${g.kind}`"
                  class="border-t"
                  style="border-color: var(--surface-3);"
                >
                  <td class="px-3 py-1.5" style="color: var(--ink);">
                    {{ groupLabel(g) }}
                    <span
                      class="ml-1 rounded px-1 py-0.5 text-[9px] uppercase"
                      :style="g.kind === 'standard'
                        ? 'background: var(--gold-100); color: var(--gold-700);'
                        : 'background: var(--surface-2); color: var(--ink-400);'"
                    >{{ g.kind === 'standard' ? 'std' : 'comm' }}</span>
                  </td>
                  <td class="px-2 py-1.5 text-right tabular-nums" style="color: var(--ink-500);">{{ g.n_searches }}</td>
                  <td class="px-2 py-1.5 text-right tabular-nums" style="color: var(--ink);">{{ g.n_summaries }}</td>
                  <td class="px-2 py-1.5 text-right tabular-nums" style="color: var(--ink);">{{ g.n_kept_results }}</td>
                  <td class="px-2 py-1.5" style="color: var(--ink-500);">
                    <span v-if="g.n_discarded_attributed === 0" style="color: var(--ink-400);">—</span>
                    <template v-else>
                      <span
                        v-for="d in g.discarded_by_reason.slice(0, 3)"
                        :key="d.reason"
                        class="mr-1 inline-block rounded px-1 py-0.5 text-[10px]"
                        style="background: var(--surface-2); color: var(--ink-500); font-family: var(--font-mono);"
                      >{{ d.reason }} {{ d.n }}</span>
                    </template>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="mt-2 text-[10px]" style="color: var(--ink-400);">
            <strong>brut</strong> = annonces renvoyées par eBay ; <strong>retenus</strong> = après
            <code>accept_listing</code> + theme-match. L'écart = listings filtrés (maille recherche,
            pré-attribution). Les <strong>jetés</strong> itemisés ne couvrent que les rejets
            rattachables au groupe ; le reste est dans l'écart brut→retenus.
          </p>
        </details>

        <!-- C8 : Dédup / Déjà-vu (informatif, lecture seule) -->
        <details class="mt-2 dedup">
          <summary class="dedup__summary">
            Dédup / Déjà-vu
            <template v-if="dedup">
              — {{ dedup.n_unique_seen.toLocaleString('fr-FR') }} vus au total
              <span v-if="dedup.n_duplicates > 0" style="color: var(--warning);">
                · {{ dedup.n_duplicates.toLocaleString('fr-FR') }} doublons discarded
              </span>
            </template>
          </summary>
          <div v-if="dedupQuery.isPending.value" class="mt-2 text-xs" style="color: var(--ink-400);">Chargement…</div>
          <template v-else-if="dedup">
            <dl class="mt-2 dedup__grid">
              <dt title="Listings distincts enregistrés dans discovery_log eBay (toutes passes, global)">Vus (discovery_log)</dt>
              <dd>{{ dedup.n_unique_seen.toLocaleString('fr-FR') }}</dd>
              <dt title="Lignes totales dans discarded_listings pour les pièces de cette cohort">Discardés (total)</dt>
              <dd>{{ dedup.n_discarded_total.toLocaleString('fr-FR') }}</dd>
              <dt title="source_ref distincts discardés — même listing revu plusieurs fois = doublon">Discardés (uniques)</dt>
              <dd>{{ dedup.n_discarded_unique.toLocaleString('fr-FR') }}</dd>
              <dt title="Doublons = total - uniques. Cause : UNIQUE(source, source_ref) manquant sur discarded_listings.">Doublons discarded</dt>
              <dd :style="{ color: dedup.n_duplicates > 0 ? 'var(--warning)' : 'var(--success)' }">
                {{ dedup.n_duplicates.toLocaleString('fr-FR') }}
              </dd>
              <dt title="Discardés uniques absents de discovery_log → re-fetch infini possible">Absents discovery_log</dt>
              <dd :style="{ color: (dedup.pct_absent ?? 0) > 50 ? 'var(--danger)' : 'var(--ink)' }">
                {{ dedup.n_absent_from_discovery.toLocaleString('fr-FR') }}
                <span v-if="dedup.pct_absent !== null" style="font-size: 10px; color: var(--ink-400);"> ({{ dedup.pct_absent }}%)</span>
              </dd>
            </dl>
            <p class="mt-2 text-[10px]" style="color: var(--ink-400);">{{ dedup.scope_note }}</p>
          </template>
        </details>

        <!-- C2 : résumé récupérabilité des rejets eBay (scopé cohort) -->
        <div
          v-if="discardSummary && discardSummary.total > 0"
          class="mt-3 rounded border px-3 py-2"
          style="border-color: var(--surface-3); background: var(--surface);"
        >
          <p class="mb-1.5 text-[10px] font-medium uppercase" style="letter-spacing: var(--tracking-eyebrow); color: var(--ink-400);">
            rejets — récupérabilité ({{ discardSummary.total }} total)
          </p>
          <div class="flex gap-2 flex-wrap">
            <span
              class="inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-medium"
              style="background: color-mix(in srgb, var(--success) 12%, transparent); color: var(--success);"
            >
              {{ discardSummary.rescue_total }} récupérables 1-clic
            </span>
            <span
              class="inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-medium"
              style="background: color-mix(in srgb, var(--danger) 10%, transparent); color: var(--danger);"
            >
              {{ discardSummary.noise_total }} vrai bruit
            </span>
            <span
              v-if="discardSummary.ambiguous_total > 0"
              class="inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-medium"
              style="background: var(--surface-2); color: var(--ink-400);"
            >
              {{ discardSummary.ambiguous_total }} ambigus
            </span>
          </div>
        </div>

      </template>
      <div v-else class="text-xs" style="color: var(--danger);">
        Erreur de chargement du statut eBay.
      </div>
    </template>
  </DrawerSection>
</template>

<style scoped>
/* Ruban funnel */
.ribbon {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 16px;
  border: 1px solid var(--surface-3);
  border-radius: 8px;
  background: var(--surface);
}
.ribbon__cell { display: flex; flex-direction: column; gap: 2px; }
.ribbon__n {
  font-family: var(--font-display);
  font-style: italic;
  font-weight: 600;
  font-size: 26px;
  line-height: 1;
  color: var(--ink);
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums lining-nums;
}
.ribbon__cell--accent .ribbon__n { color: var(--indigo-700); }
.ribbon__lbl {
  font-family: var(--font-mono);
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: var(--tracking-eyebrow);
  color: var(--ink-400);
}
.ribbon__arr { font-size: 18px; color: var(--ink-300); }
.ribbon__aside {
  margin-left: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
  text-align: right;
  font-size: 11px;
  color: var(--ink-400);
}
.ribbon__aside b { font-family: var(--font-mono); color: var(--ink-500); }

/* Row-card par coin */
.coin {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 11px 14px;
  background: var(--surface);
}
.coin + .coin { border-top: 1px solid var(--surface-3); }
.coin__l1 {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}
.coin__id {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--ink);
  min-width: 0;
}
.coin__badge {
  margin-right: 4px;
  border-radius: 3px;
  padding: 1px 4px;
  font-size: 9px;
  text-transform: uppercase;
  background: var(--surface-2);
  color: var(--ink-400);
}
/* Badge jamais-scrapé */
.coin__badge--danger {
  background: color-mix(in srgb, var(--danger) 12%, var(--surface));
  color: var(--danger);
}
/* Badge « 0 attribué » (B1) — groupe scrapé mais rien reçu (dispersé sœurs). */
.coin__badge--warn {
  background: color-mix(in srgb, var(--warning) 14%, var(--surface));
  color: var(--warning);
}
.coin__sources {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--ink-400);
  white-space: nowrap;
}
/* Barre de progression enrichissement */
.coin__proj { display: flex; align-items: center; gap: 5px; }
.coin__proj-bar {
  width: 52px;
  height: 4px;
  border-radius: 2px;
  background: var(--surface-3);
  overflow: hidden;
}
.coin__proj-fill { display: block; height: 100%; border-radius: 2px; transition: width 300ms ease; }
.coin__proj b { font-size: 11px; font-variant-numeric: tabular-nums; font-weight: 600; }
.coin__proj-detail {
  font-family: var(--font-mono);
  font-size: 9px;
  color: var(--ink-400);
  white-space: nowrap;
}

.coin__funnel {
  font-size: 12.5px;
  color: var(--ink-500);
  font-variant-numeric: tabular-nums;
}
.coin__funnel b { color: var(--ink); font-weight: 600; }
.coin__arr { margin: 0 5px; color: var(--ink-300); }
.coin__dot { margin: 0 6px; color: var(--ink-300); }

.coin__actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.coin__btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border-radius: 4px;
  padding: 3px 8px;
  font-size: 10px;
  font-weight: 500;
  color: var(--indigo-700);
  background: color-mix(in srgb, var(--indigo-700) 9%, var(--surface));
  transition: background 160ms var(--ease-out, ease);
}
.coin__btn:hover { background: color-mix(in srgb, var(--indigo-700) 16%, var(--surface)); }
/* Action PRIMAIRE (F2) : plein indigo, dominant. Une seule par row max → l'œil
   sait quoi faire sans lire 5 boutons à poids égal. Override coin__btn (ordre
   source). */
.coin__btn--primary {
  color: white;
  background: var(--indigo-700);
  font-weight: 600;
  padding: 4px 10px;
}
.coin__btn--primary:hover { background: var(--indigo-700); filter: brightness(1.08); }
/* Bouton scrape (consomme le quota) : ton plus neutre pour le distinguer des
   actions locales gratuites (Reviewer / Recropper). */
.coin__btn--scrape {
  color: var(--ink-500);
  background: var(--surface-2);
}
.coin__btn--scrape:hover { background: var(--surface-3); }
/* Recrop épuisé (job done à 0 crop) — grisé, non cliquable, plus de zombie. */
.coin__btn--exhausted {
  color: var(--ink-400);
  background: var(--surface-2);
  cursor: default;
  font-style: italic;
}
/* Job recrop en cours : barre de progression in-row (lue depuis cohort_jobs). */
.coin__job {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 10px;
  color: var(--indigo-700);
}
.coin__job-bar {
  width: 56px;
  height: 4px;
  border-radius: 2px;
  background: var(--surface-3);
  overflow: hidden;
}
.coin__job-fill {
  display: block;
  height: 100%;
  border-radius: 2px;
  background: var(--indigo-700);
  transition: width 300ms ease;
}
.coin__job-lbl { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
.coin__audit {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  border-radius: 4px;
  padding: 3px 8px;
  font-size: 10px;
  font-weight: 500;
  color: var(--indigo-700);
  text-decoration: none;
  background: color-mix(in srgb, var(--indigo-700) 8%, var(--surface));
  transition: background 160ms var(--ease-out, ease);
}
.coin__audit:hover { background: color-mix(in srgb, var(--indigo-700) 16%, var(--surface)); }
.coin__audit--muted { color: var(--ink-500); background: var(--surface-2); }
.coin__audit--muted:hover { background: var(--surface-3); }
.coin__muted { font-size: 10px; color: var(--ink-400); }

/* Badge run live */
.live-badge {
  margin-top: 8px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border-radius: 4px;
  padding: 4px 10px;
  font-size: 11px;
  background: color-mix(in srgb, var(--indigo-700) 10%, var(--surface));
  color: var(--indigo-700);
}

/* F4 — ligne-exemple annotée (légende) */
.legend {
  border: 1px dashed var(--surface-3);
  border-radius: 8px;
  padding: 8px 14px 12px;
  background: color-mix(in srgb, var(--surface-1) 50%, var(--surface));
}
.legend__summary {
  cursor: pointer;
  font-size: 11px;
  font-weight: 600;
  color: var(--ink-500);
  user-select: none;
  text-transform: uppercase;
  letter-spacing: var(--tracking-eyebrow);
}
.legend__summary:hover { color: var(--ink); }
.legend__example {
  margin-top: 10px;
  padding: 10px 12px;
  border: 1px solid var(--surface-3);
  border-radius: 6px;
  background: var(--surface);
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.legend__key {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 4px 14px;
  margin: 12px 0 0;
  font-size: 11px;
}
.legend__key dt { color: var(--ink); white-space: nowrap; }
.legend__key dt b { font-variant-numeric: tabular-nums; }
.legend__key dd { margin: 0; color: var(--ink-400); }
.legend__chip {
  display: inline-block;
  border-radius: 3px;
  padding: 0 5px;
  font-size: 9px;
  background: var(--surface-2);
  color: var(--ink-500);
}
.legend__chip--primary { background: var(--indigo-700); color: white; }

/* Découverte */
.head__summary {
  cursor: pointer;
  font-size: 11px;
  font-weight: 500;
  color: var(--ink-500);
  user-select: none;
}
.head__summary:hover { color: var(--ink); }

/* Dédup / Déjà-vu (C8) */
.dedup__summary {
  cursor: pointer;
  font-size: 11px;
  font-weight: 500;
  color: var(--ink-500);
  user-select: none;
}
.dedup__summary:hover { color: var(--ink); }
.dedup__grid {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 3px 16px;
  font-size: 11px;
}
.dedup__grid dt { color: var(--ink-400); }
.dedup__grid dd { font-family: var(--font-mono); font-variant-numeric: tabular-nums; color: var(--ink); }

/* Rescue cross-classe (pièces sœurs hors cohort) — ton neutre, c'est du travail
   fait, pas un gap. */
.sisters {
  border: 1px solid var(--surface-3);
  border-radius: 6px;
  padding: 6px 12px;
  background: var(--surface);
}
.sisters__summary {
  cursor: pointer;
  font-size: 11px;
  color: var(--ink-500);
  user-select: none;
}
.sisters__summary:hover { color: var(--ink); }
.sisters__list {
  margin: 8px 0 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.sisters__list li {
  display: flex;
  align-items: center;
  gap: 6px;
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--ink-500);
}
.sisters__src { color: var(--ink-400); }
.sisters__arr { color: var(--ink-300); }
.sisters__dst { color: var(--ink); }
.sisters__n {
  margin-left: auto;
  font-variant-numeric: tabular-nums;
  color: var(--ink-400);
}
.sisters__note {
  margin-top: 8px;
  font-size: 10px;
  color: var(--ink-400);
}
</style>
