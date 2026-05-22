<script setup lang="ts">
// Vue Single du flow review (extraite de ReviewPage.vue lors du
// refacto Phase 2 R.0 — 2026-05-04). Contient la logique historique
// inchangée : queue + item courant + action bar + toast undo + help
// overlay + sélecteur libre. Le shell ReviewPage gère le toggle
// Single | Lot et le titre.

import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { AlertTriangle, Keyboard, Search, Sparkles, Undo2 } from 'lucide-vue-next'
import {
  correctListing,
  decideReviewItem,
  fetchMarketQuotes,
  fetchReviewQueue,
  fetchReviewStats,
  rejectReviewItem,
  skipReviewItem,
  type ConditionTier,
  type ListingKind,
  type MarketQuote,
  type ReviewCandidate,
  type ReviewDecision,
  type ReviewFace,
  type ReviewItem,
  type ReviewStats,
} from '../composables/useReviewApi'
import { useReviewKeybinds } from '../composables/useReviewKeybinds'
import type { CoinSearchEntry } from '../composables/useCoinsSearch'
import SplitCompare from '../components/SplitCompare.vue'
import ReviewActionBar from '../components/ReviewActionBar.vue'
import DinoVerdict from '../components/DinoVerdict.vue'
import AutoValidateVerdict from '../components/AutoValidateVerdict.vue'
import ReviewRightColumn from '../components/ReviewRightColumn.vue'
import ListingContextCard from '../components/ListingContextCard.vue'
import TextSignals from '../components/TextSignals.vue'

// Ordre de cycle des corrections clavier (K / C).
const KIND_CYCLE: ListingKind[] = ['single', 'lot', 'coffret', 'graded_slab']
const CONDITION_CYCLE: ConditionTier[] = ['UNC', 'TTB', 'TB']
import type { DinoSuggestion } from '../composables/useDinoSuggestions'

// ─── State ──────────────────────────────────────────────────────────────

const queue = ref<ReviewItem[]>([])
const currentIndex = ref(0)
const focusedCandidateIdx = ref<number | null>(null)
const freeSearchCandidate = ref<ReviewCandidate | null>(null)
const face = ref<ReviewFace>('obverse')
const stats = ref<ReviewStats | null>(null)
const showHelp = ref(false)
// Mode de la colonne droite : 'auto' = Top N + DinoSuggestions ;
// 'free' = FreeSelectorPanel inline (cascade pays/dénom/année).
// Reset à 'auto' à chaque changement d'item.
const mode = ref<'auto' | 'free'>('auto')
// ─── Commit différé (modèle « undo Send ») ──────────────────────────────
// Une action (validate / reject / skip) n'est PAS POSTée immédiatement :
// elle devient une décision « en attente » et n'est commitée qu'après
// COMMIT_WINDOW_MS. Pendant la fenêtre, « Annuler » la supprime sans
// qu'aucune écriture serveur n'ait eu lieu — donc plus de re-décision
// d'un item déjà `done` (cf. bug 409). Au plus une décision en attente :
// une nouvelle action flush la précédente avant de s'armer.
const COMMIT_WINDOW_MS = 10_000

type PendingKind = 'decide' | 'reject' | 'skip'

interface PendingCommit {
  kind: PendingKind
  reviewId: string
  /** Index de l'item dans `queue` — sert au rewind exact de l'undo. */
  itemIndex: number
  /** Payload de décision (kind='decide' uniquement). */
  payload?: ReviewDecision
}

const PENDING_LABEL: Record<PendingKind, string> = {
  decide: 'Pièce validée',
  reject: 'Image rejetée',
  skip: 'Review reportée',
}

const pendingCommit = ref<PendingCommit | null>(null)
let commitTimer: ReturnType<typeof setTimeout> | null = null
// Bumpé à chaque action — sert de `key` au toast pour relancer son
// animation de compte à rebours même sur deux actions consécutives.
const toastNonce = ref(0)

// Bandeau d'alerte qui descend du haut de l'écran — feedback quand on
// presse ⏎ alors que la validation est bloquée.
const topNotice = ref<string | null>(null)
let topNoticeTimer: ReturnType<typeof setTimeout> | null = null

// Correction opt-in du contexte listing (C4). `null` = on garde la
// valeur heuristique C2 ; sinon = valeur corrigée à la main. Reset à
// chaque item. Flushé vers l'API au passage à l'item suivant.
const correctedKind = ref<ListingKind | null>(null)
const correctedCondition = ref<ConditionTier | null>(null)
// Quotes marché des candidats de l'item courant (clé = eurio_id).
const marketQuotes = ref<Record<string, MarketQuote[]>>({})

// ─── Derived ────────────────────────────────────────────────────────────

const currentItem = computed<ReviewItem | null>(
  () => queue.value[currentIndex.value] ?? null,
)

const focusedCandidate = computed<ReviewCandidate | null>(() => {
  if (freeSearchCandidate.value) return freeSearchCandidate.value
  if (focusedCandidateIdx.value === null || !currentItem.value) return null
  return currentItem.value.candidates[focusedCandidateIdx.value] ?? null
})

const isQueueEmpty = computed(() => currentIndex.value >= queue.value.length)

// Valeurs affichées sur la carte listing : correction manuelle si elle
// existe, sinon l'heuristique C2.
const effectiveKind = computed<ListingKind | null>(
  () => correctedKind.value ?? currentItem.value?.listing_kind ?? null,
)
const effectiveCondition = computed<ConditionTier | null>(
  () => correctedCondition.value ?? currentItem.value?.condition ?? null,
)

// Quote marché pour la pièce du candidat focusé + l'état courant du
// listing — alimente le cross-check prix de la carte.
const focusedMarketQuote = computed<MarketQuote | null>(() => {
  const eid = focusedCandidate.value?.eurio_id
  const cond = effectiveCondition.value
  if (!eid || !cond) return null
  return (marketQuotes.value[eid] ?? []).find((q) => q.condition === cond) ?? null
})

// Valider exige un candidat ET un type/état renseignés : on ne fige pas
// une attribution sans avoir tranché le contexte listing (C4).
const canValidate = computed(
  () => !!focusedCandidate.value
    && effectiveKind.value !== null
    && effectiveCondition.value !== null,
)
const validateBlockedReason = computed<string | null>(() => {
  if (!focusedCandidate.value) {
    return 'Sélectionne un candidat (1-5) ou le sélecteur libre (F)'
  }
  if (effectiveKind.value === null || effectiveCondition.value === null) {
    return 'Renseigne le type (K) et l’état (C) du listing'
  }
  return null
})

// ─── Loaders ────────────────────────────────────────────────────────────

async function load() {
  const [q, s] = await Promise.all([fetchReviewQueue({ limit: 30 }), fetchReviewStats()])
  queue.value = q
  stats.value = s
  resetForCurrent()
}

function resetForCurrent() {
  freeSearchCandidate.value = null
  mode.value = 'auto'
  correctedKind.value = null
  correctedCondition.value = null
  void loadMarketQuotes()
  // Pré-sélection : la pièce proposée (target_candidate, theme-match) bat
  // le top-1 auto-name. ~80 % des reviews valident la proposition —
  // pré-sélectionner évite un clic dans la majorité des cas.
  const target = currentItem.value?.target_candidate ?? null
  if (target) {
    freeSearchCandidate.value = target
    focusedCandidateIdx.value = null
  } else {
    const top1 = currentItem.value?.candidates[0]
    focusedCandidateIdx.value = top1 && top1.score >= 0.5 ? 0 : null
  }
  face.value = currentItem.value?.face_detected ?? 'obverse'
}

function selectTarget() {
  const target = currentItem.value?.target_candidate ?? null
  if (!target) return
  freeSearchCandidate.value = target
  focusedCandidateIdx.value = null
}

// Commit garanti même si l'onglet se ferme pendant la fenêtre d'undo :
// `keepalive` laisse le POST se terminer après l'unload.
function flushBeforeUnload() {
  flushPending({ keepalive: true })
}

onMounted(() => {
  void load()
  window.addEventListener('beforeunload', flushBeforeUnload)
})

// Démontage = changement de route OU bascule Single→Lot (v-if dans
// ReviewPage) : on flush la décision en attente plutôt que la perdre.
onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', flushBeforeUnload)
  flushPending()
})

// ─── Actions ────────────────────────────────────────────────────────────

function focusCandidate(idx: number) {
  if (!currentItem.value) return
  if (idx < 0 || idx >= currentItem.value.candidates.length) return
  focusedCandidateIdx.value = idx
  freeSearchCandidate.value = null
}

function setFace(f: ReviewFace) {
  face.value = f
}

function advance() {
  flushCorrection()
  currentIndex.value += 1
  resetForCurrent()
}

/** Charge les quotes marché des candidats de l'item courant. */
async function loadMarketQuotes() {
  marketQuotes.value = {}
  const item = currentItem.value
  if (!item) return
  const ids = new Set<string>()
  if (item.target_candidate) ids.add(item.target_candidate.eurio_id)
  item.candidates.forEach((c) => ids.add(c.eurio_id))
  ;(item.group_candidates ?? []).forEach((c) => ids.add(c.eurio_id))
  if (ids.size === 0) return
  marketQuotes.value = await fetchMarketQuotes([...ids])
}

/** POST la correction listing si l'utilisateur a touché K / C. */
function flushCorrection() {
  const item = currentItem.value
  if (!item) return
  if (correctedKind.value === null && correctedCondition.value === null) return
  // Fire-and-forget : une correction d'audit ne bloque pas le flow.
  void correctListing(item.id, {
    listing_kind: correctedKind.value ?? undefined,
    condition: correctedCondition.value ?? undefined,
  })
}

function cycleKind() {
  if (!currentItem.value) return
  // Première frappe sur un listing sans type (—) → 1ʳᵉ valeur, pas le
  // cran suivant. Ensuite, cycle normal.
  const cur = effectiveKind.value
  correctedKind.value = cur === null
    ? KIND_CYCLE[0]
    : KIND_CYCLE[(KIND_CYCLE.indexOf(cur) + 1) % KIND_CYCLE.length]
}

function cycleCondition() {
  if (!currentItem.value) return
  const cur = effectiveCondition.value
  correctedCondition.value = cur === null
    ? CONDITION_CYCLE[0]
    : CONDITION_CYCLE[(CONDITION_CYCLE.indexOf(cur) + 1) % CONDITION_CYCLE.length]
}

function flashTopNotice(message: string) {
  if (topNoticeTimer) clearTimeout(topNoticeTimer)
  topNotice.value = message
  topNoticeTimer = setTimeout(() => {
    topNotice.value = null
  }, 2800)
}

function validateCurrent() {
  if (!currentItem.value) return
  if (!canValidate.value) {
    // ⏎ pressé mais validation bloquée → feedback visible.
    flashTopNotice(validateBlockedReason.value ?? 'Validation bloquée')
    return
  }
  if (!focusedCandidate.value) return  // garanti par canValidate — narrowing TS
  scheduleCommit('decide', currentItem.value.id, {
    eurio_id: focusedCandidate.value.eurio_id,
    face: face.value,
  })
  advance()
}

function rejectCurrent() {
  if (!currentItem.value) return
  scheduleCommit('reject', currentItem.value.id)
  advance()
}

function skipCurrent() {
  if (!currentItem.value) return
  scheduleCommit('skip', currentItem.value.id)
  advance()
}

// ─── Commit différé : scheduling / flush / undo ─────────────────────────

/** POST réel d'une décision. Tout échec est surfacé via le bandeau —
 *  jamais d'exception non catchée (cf. bug 409 décrit en aparté). */
async function commitPending(p: PendingCommit, opts: { keepalive?: boolean } = {}) {
  try {
    if (p.kind === 'decide' && p.payload) {
      await decideReviewItem(p.reviewId, p.payload, opts)
    } else if (p.kind === 'reject') {
      await rejectReviewItem(p.reviewId, opts)
    } else if (p.kind === 'skip') {
      await skipReviewItem(p.reviewId, opts)
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    flashTopNotice(`Échec de l'enregistrement : ${msg}`)
  }
}

/** Commit immédiat de la décision en attente (timer écoulé, nouvelle
 *  action, démontage de la vue). Idempotent : sans pending, no-op. */
function flushPending(opts: { keepalive?: boolean } = {}) {
  if (!pendingCommit.value) return
  if (commitTimer) { clearTimeout(commitTimer); commitTimer = null }
  const p = pendingCommit.value
  pendingCommit.value = null
  void commitPending(p, opts)
}

/** Diffère une action : flush la précédente, arme le timer de commit. */
function scheduleCommit(kind: PendingKind, reviewId: string, payload?: ReviewDecision) {
  flushPending()
  pendingCommit.value = { kind, reviewId, itemIndex: currentIndex.value, payload }
  toastNonce.value++
  commitTimer = setTimeout(() => {
    commitTimer = null
    const p = pendingCommit.value
    pendingCommit.value = null
    if (p) void commitPending(p)
  }, COMMIT_WINDOW_MS)
}

/** Annule la décision en attente — aucune écriture n'a eu lieu, on
 *  rembobine simplement le curseur sur l'item concerné. */
function undoLast() {
  const p = pendingCommit.value
  if (!p) return
  if (commitTimer) { clearTimeout(commitTimer); commitTimer = null }
  pendingCommit.value = null
  currentIndex.value = p.itemIndex
  resetForCurrent()
}

function toggleMode() {
  mode.value = mode.value === 'auto' ? 'free' : 'auto'
}

function closeSearchOverlay() {
  if (showHelp.value) {
    showHelp.value = false
    return
  }
  if (mode.value === 'free') {
    mode.value = 'auto'
  }
}

function onSearchSelect(entry: CoinSearchEntry) {
  freeSearchCandidate.value = {
    eurio_id: entry.eurio_id,
    score: 1.0,
    label: entry.label,
    country: entry.country,
    denomination: entry.denomination,
    year: entry.year,
    canonical_thumb_url: entry.canonical_thumb_url ?? '',
  }
  focusedCandidateIdx.value = null
  // Une pièce a été pickée → repasse en mode auto pour montrer le banner
  // freeSearchCandidate + permettre la validation immédiate (⏎).
  mode.value = 'auto'
}

function onGroupSelect(c: ReviewCandidate) {
  // Pièce du groupe pickée (listing ambigu, pas de proposition) — même
  // voie que la sélection libre : devient le candidat focusé, validable
  // immédiatement (⏎).
  freeSearchCandidate.value = c
  focusedCandidateIdx.value = null
}

function onDinoSelect(s: DinoSuggestion) {
  // Convertit une suggestion Dino en pseudo-ReviewCandidate puis prend
  // la voie "free search" (même UX que le sélecteur libre F).
  freeSearchCandidate.value = {
    eurio_id: s.eurio_id,
    score: s.sim,
    label: [s.country_name, s.year, s.theme].filter(Boolean).join(' · '),
    country: s.country ?? '',
    denomination: s.denomination ? `${s.denomination} EUR` : '',
    year: s.year,
    canonical_thumb_url: s.obverse_url ?? '',
  }
  focusedCandidateIdx.value = null
}

// ─── Keyboard ───────────────────────────────────────────────────────────

const keyboardEnabled = computed(() => !showHelp.value)

useReviewKeybinds(keyboardEnabled, {
  onCandidateFocus: focusCandidate,
  onValidate: validateCurrent,
  onReject: rejectCurrent,
  onSkip: skipCurrent,
  onOpenSearch: toggleMode,
  onCloseOverlay: closeSearchOverlay,
  onSetFace: setFace,
  onCycleKind: cycleKind,
  onCycleCondition: cycleCondition,
})
</script>

<template>
  <div class="flex flex-1 flex-col overflow-hidden">
    <!-- ═══ Sub-header : stats + actions ═══ -->
    <div
      class="flex flex-wrap items-center justify-between gap-4 border-b px-8 py-2.5"
      style="border-color: var(--surface-3); background: var(--surface);"
    >
      <div
        v-if="stats"
        class="flex items-center gap-5 font-mono text-[11px] tabular-nums"
        style="color: var(--ink-500);"
      >
        <span>
          <span class="font-semibold" style="color: var(--indigo-700);">{{ stats.n_done_today }}</span>
          <span class="ml-1 uppercase tracking-wider" style="color: var(--ink-400);">today</span>
        </span>
        <span class="opacity-50">·</span>
        <span>
          <span class="font-semibold" style="color: var(--ink);">{{ stats.median_seconds_per_decision.toFixed(1) }}s</span>
          <span class="ml-1 uppercase tracking-wider" style="color: var(--ink-400);">median</span>
        </span>
        <span class="opacity-50">·</span>
        <span>
          <span class="font-semibold" style="color: var(--ink);">{{ stats.n_pending.toLocaleString('fr-FR') }}</span>
          <span class="ml-1 uppercase tracking-wider" style="color: var(--ink-400);">left</span>
        </span>
      </div>
      <div v-else />

      <div class="flex items-center gap-2">
        <div
          class="mode-toggle inline-flex overflow-hidden rounded-md border"
          style="border-color: var(--surface-3); background: var(--surface-1);"
          :title="'Bascule mode · F'"
        >
          <button
            type="button"
            class="mode-btn"
            :class="{ active: mode === 'auto' }"
            @click="mode = 'auto'"
          >
            <Sparkles class="h-3 w-3" />
            Auto
          </button>
          <button
            type="button"
            class="mode-btn"
            :class="{ active: mode === 'free' }"
            @click="mode = 'free'"
          >
            <Search class="h-3 w-3" />
            Libre
            <span class="ml-1 font-mono text-[9px] uppercase tracking-wider opacity-70">F</span>
          </button>
        </div>
        <button
          type="button"
          class="inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px]"
          style="border-color: var(--surface-3); color: var(--ink-500); background: var(--surface-1);"
          @click="showHelp = !showHelp"
        >
          <Keyboard class="h-3 w-3" />
          ?
        </button>
      </div>
    </div>

    <!-- ═══ Empty state ═══ -->
    <section
      v-if="isQueueEmpty"
      class="flex flex-1 flex-col items-center justify-center px-8 py-16 text-center"
    >
      <p
        class="font-display text-5xl italic font-semibold"
        style="color: var(--indigo-700);"
      >
        Tout est résolu.
      </p>
      <p class="mt-4 max-w-md text-sm" style="color: var(--ink-500);">
        La queue est vide. La nouvelle ronde de scrapes alimentera la review
        à la prochaine cadence (cf. <code style="background: var(--surface-1); padding: 1px 4px; border-radius: 3px;">/sources</code>).
      </p>
      <p
        v-if="stats"
        class="mt-8 font-mono text-[10px] uppercase tracking-wider"
        style="color: var(--ink-400);"
      >
        {{ stats.n_done_this_week }} décidées cette semaine · {{ stats.median_seconds_per_decision.toFixed(1) }}s par décision en moyenne
      </p>
    </section>

    <!-- ═══ Review item ═══ -->
    <section
      v-else-if="currentItem"
      class="flex flex-1 flex-col overflow-hidden"
    >
      <div class="grid flex-1 gap-6 overflow-hidden px-8 py-6 lg:grid-cols-[minmax(0,1fr)_560px]">
          <!-- ── COLONNE GAUCHE ── -->
          <div class="flex min-h-0 flex-col gap-4 overflow-y-auto">
            <SplitCompare
              :crop-url="currentItem.crop_url"
              :canonical-url="focusedCandidate?.canonical_thumb_url ?? null"
              :bbox="currentItem.bbox"
            />

            <ListingContextCard
              :title="currentItem.listing_title"
              :source="currentItem.source"
              :price="currentItem.listing_price"
              :kind="effectiveKind"
              :kind-confidence="currentItem.listing_kind_confidence ?? null"
              :kind-corrected="correctedKind !== null"
              :condition="effectiveCondition"
              :condition-confidence="currentItem.condition_confidence ?? null"
              :condition-corrected="correctedCondition !== null"
              :origin-date="currentItem.listing_origin_date ?? null"
              :sold-qty="currentItem.sold_qty ?? null"
              :market-quote="focusedMarketQuote"
            />

            <AutoValidateVerdict
              v-if="currentItem"
              :review-id="currentItem.id"
            />

            <TextSignals
              v-if="currentItem"
              :review-id="currentItem.id"
              variant="standard"
            />

            <DinoVerdict
              v-if="currentItem"
              :review-id="currentItem.id"
              variant="standard"
            />
          </div>

          <!-- ── COLONNE DROITE (composant partagé avec lot) ── -->
          <ReviewRightColumn
            :target="currentItem.target_candidate ?? null"
            :candidates="currentItem.candidates"
            :group-candidates="currentItem.group_candidates ?? []"
            :mode="mode"
            :focused-candidate-idx="focusedCandidateIdx"
            :free-search-candidate="freeSearchCandidate"
            :review-id="currentItem.id"
            @target-focus="selectTarget"
            @candidate-focus="focusCandidate"
            @dino-select="onDinoSelect"
            @free-select="onSearchSelect"
            @group-select="onGroupSelect"
          />
      </div>

      <ReviewActionBar
        :face="face"
        :can-validate="canValidate"
        :validate-hint="validateBlockedReason"
        :focused-eurio-id="focusedCandidate?.eurio_id ?? null"
        @face="setFace"
        @validate="validateCurrent"
        @reject="rejectCurrent"
        @skip="skipCurrent"
      />
    </section>

    <!-- ═══ Bandeau d'alerte (descend du haut) ═══ -->
    <Transition name="topnotice">
      <div
        v-if="topNotice"
        class="fixed left-1/2 top-0 z-40 -translate-x-1/2 inline-flex items-center gap-2.5 rounded-b-xl px-7 py-3.5 text-[14px] font-semibold shadow-xl"
        style="background: var(--warning); color: var(--ink);"
      >
        <AlertTriangle class="h-5 w-5" />
        {{ topNotice }}
      </div>
    </Transition>

    <!-- ═══ Toast undo — fenêtre de COMMIT_WINDOW_MS avant écriture ═══ -->
    <Transition name="toast">
      <div
        v-if="pendingCommit"
        :key="toastNonce"
        class="fixed bottom-20 left-1/2 z-20 -translate-x-1/2 inline-flex items-center gap-3 overflow-hidden rounded-full border px-4 py-2 text-[12px] shadow-lg"
        style="border-color: var(--surface-3); background: var(--ink); color: var(--surface);"
      >
        <span>
          <strong>{{ PENDING_LABEL[pendingCommit.kind] }}</strong>
          <span class="opacity-60">· enregistrement dans {{ COMMIT_WINDOW_MS / 1000 }} s</span>
        </span>
        <button
          type="button"
          class="inline-flex items-center gap-1 rounded-md px-2 py-0.5 font-mono text-[11px] transition-colors"
          style="background: var(--surface); color: var(--ink);"
          @click="undoLast"
        >
          <Undo2 class="h-3 w-3" /> Annuler
        </button>
        <!-- Compte à rebours CSS pur — aucun timer JS à nettoyer. -->
        <span
          class="undo-countdown"
          :style="{ animationDuration: COMMIT_WINDOW_MS + 'ms' }"
        />
      </div>
    </Transition>

    <!-- ═══ Help overlay ═══ -->
    <div
      v-if="showHelp"
      class="fixed inset-0 z-30 flex items-center justify-center px-6"
      style="background: rgba(14,14,31,.65); backdrop-filter: blur(4px);"
      @click="showHelp = false"
    >
      <article
        class="max-w-md rounded-lg border p-6"
        style="border-color: var(--surface-3); background: var(--surface);"
        @click.stop
      >
        <h2 class="font-display text-lg italic font-semibold" style="color: var(--indigo-700);">
          Raccourcis
        </h2>
        <dl class="mt-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">1 – 5</dt>
          <dd style="color: var(--ink-500);">Focus candidat</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">⏎</dt>
          <dd style="color: var(--ink-500);">Valider avec candidat focusé</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">R</dt>
          <dd style="color: var(--ink-500);">Reject (image inutilisable)</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">N</dt>
          <dd style="color: var(--ink-500);">Skip (repousser)</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">F</dt>
          <dd style="color: var(--ink-500);">Bascule mode Auto / Sélection libre</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">O / V / U</dt>
          <dd style="color: var(--ink-500);">Face : avers / revers / inconnu</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">K</dt>
          <dd style="color: var(--ink-500);">Corriger le type de listing (cycle)</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">C</dt>
          <dd style="color: var(--ink-500);">Corriger l'état de la pièce (cycle)</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">Esc</dt>
          <dd style="color: var(--ink-500);">Fermer overlay</dd>
        </dl>
        <p class="mt-5 text-[11px]" style="color: var(--ink-400);">
          Cliquer ailleurs ou <kbd
            class="mx-1 inline-block rounded px-1 py-0.5 font-mono text-[10px]"
            style="background: var(--surface-1); border: 1px solid var(--surface-3);"
          >Esc</kbd> pour fermer.
        </p>
      </article>
    </div>

  </div>
</template>

<style scoped>
@keyframes fade-in {
  from {
    opacity: 0;
    transform: translateX(6px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

.toast-enter-active,
.toast-leave-active {
  transition: all 200ms ease-out;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translate(-50%, 8px);
}

/* Bandeau d'alerte : glisse depuis au-dessus de l'écran, s'arrête au top. */
.topnotice-enter-active,
.topnotice-leave-active {
  transition: opacity 220ms ease-out, transform 260ms cubic-bezier(0.16, 1, 0.3, 1);
}
.topnotice-enter-from,
.topnotice-leave-to {
  opacity: 0;
  transform: translate(-50%, -100%);
}

kbd {
  font-family: ui-monospace, SFMono-Regular, monospace;
}

/* Compte à rebours du toast undo : barre qui se vide en COMMIT_WINDOW_MS
   (durée posée inline). CSS pur — aucun timer JS à nettoyer. */
.undo-countdown {
  position: absolute;
  left: 0;
  bottom: 0;
  height: 2px;
  width: 100%;
  background: var(--gold-soft);
  transform-origin: left;
  animation-name: undo-countdown;
  animation-timing-function: linear;
  animation-fill-mode: forwards;
}
@keyframes undo-countdown {
  from {
    transform: scaleX(1);
  }
  to {
    transform: scaleX(0);
  }
}

.mode-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  font-size: 11px;
  color: var(--ink-500);
  background: transparent;
  cursor: pointer;
  transition: all 140ms ease;
}
.mode-btn:hover {
  color: var(--ink-700);
}
.mode-btn.active {
  color: var(--surface);
  background: var(--ink);
}
.mode-btn + .mode-btn {
  border-left: 0.5px solid var(--surface-3);
}
</style>
