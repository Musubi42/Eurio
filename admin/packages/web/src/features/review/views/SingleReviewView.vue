<script setup lang="ts">
// Vue Single du flow review (extraite de ReviewPage.vue lors du
// refacto Phase 2 R.0 — 2026-05-04). Contient la logique historique
// inchangée : queue + item courant + action bar + toast undo + help
// overlay + sélecteur libre. Le shell ReviewPage gère le toggle
// Single | Lot et le titre.

import { computed, onMounted, ref } from 'vue'
import { Keyboard, Search, Sparkles, Undo2 } from 'lucide-vue-next'
import {
  decideReviewItem,
  fetchReviewQueue,
  fetchReviewStats,
  rejectReviewItem,
  skipReviewItem,
  type ReviewCandidate,
  type ReviewFace,
  type ReviewItem,
  type ReviewStats,
} from '../composables/useReviewApi'
import { useReviewKeybinds } from '../composables/useReviewKeybinds'
import type { CoinSearchEntry } from '../composables/useCoinsSearch'
import CandidateRow from '../components/CandidateRow.vue'
import SplitCompare from '../components/SplitCompare.vue'
import ReviewActionBar from '../components/ReviewActionBar.vue'
import DinoSuggestions from '../components/DinoSuggestions.vue'
import DinoVerdict from '../components/DinoVerdict.vue'
import AutoValidateVerdict from '../components/AutoValidateVerdict.vue'
import FreeSelectorPanel from '../components/FreeSelectorPanel.vue'
import TextSignals from '../components/TextSignals.vue'
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
const undoToast = ref<{ id: string; action: 'reject' | 'skip' } | null>(null)
let undoTimer: ReturnType<typeof setTimeout> | null = null

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
  // Pré-sélection : la cible eBay (target_candidate) bat le top-1
  // auto-name. ~80 % des reviews valident la cible — pré-sélectionner
  // évite un clic dans la majorité des cas.
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

onMounted(() => {
  void load()
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
  currentIndex.value += 1
  resetForCurrent()
}

async function validateCurrent() {
  if (!currentItem.value || !focusedCandidate.value) return
  await decideReviewItem(currentItem.value.id, {
    eurio_id: focusedCandidate.value.eurio_id,
    face: face.value,
  })
  advance()
}

async function rejectCurrent() {
  if (!currentItem.value) return
  const id = currentItem.value.id
  await rejectReviewItem(id)
  showUndoToast(id, 'reject')
  advance()
}

async function skipCurrent() {
  if (!currentItem.value) return
  const id = currentItem.value.id
  await skipReviewItem(id)
  showUndoToast(id, 'skip')
  advance()
}

function showUndoToast(id: string, action: 'reject' | 'skip') {
  if (undoTimer) clearTimeout(undoTimer)
  undoToast.value = { id, action }
  undoTimer = setTimeout(() => {
    undoToast.value = null
  }, 5000)
}

function undoLast() {
  // V1 mock — on remet l'item au début de la queue (pas de vrai rollback API)
  if (!undoToast.value) return
  const id = undoToast.value.id
  const item = queue.value.find((r) => r.id === id)
  if (item) {
    currentIndex.value = Math.max(0, currentIndex.value - 1)
    resetForCurrent()
  }
  undoToast.value = null
  if (undoTimer) clearTimeout(undoTimer)
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

            <article
              class="rounded-lg border px-4 py-3"
              style="border-color: var(--surface-3); background: var(--surface);"
            >
              <p
                class="font-mono text-[10px] uppercase tracking-wider"
                style="color: var(--ink-500);"
              >
                Listing source
              </p>
              <p
                class="mt-1 font-display text-sm italic"
                style="color: var(--ink);"
              >
                « {{ currentItem.listing_title }} »
              </p>
              <div
                class="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1 font-mono text-[11px]"
                style="color: var(--ink-500);"
              >
                <span>
                  <span class="opacity-70">source&nbsp;·</span>
                  <span class="ml-1" style="color: var(--ink-700);">{{ currentItem.source }}</span>
                </span>
                <span>
                  <span class="opacity-70">ref&nbsp;·</span>
                  <span class="ml-1" style="color: var(--ink-700);">{{ currentItem.source_ref }}</span>
                </span>
                <span v-if="currentItem.listing_price !== null">
                  <span class="opacity-70">prix&nbsp;·</span>
                  <span class="ml-1" style="color: var(--ink-700);">{{ currentItem.listing_price.toFixed(2) }}€</span>
                </span>
                <span v-if="currentItem.is_multi_coin_lot">
                  <span style="color: var(--warning);">lot multi-pièces</span>
                </span>
                <span>
                  <span class="opacity-70">qualité&nbsp;·</span>
                  <span class="ml-1" style="color: var(--ink-700);">{{ currentItem.quality_score.toFixed(2) }}</span>
                </span>
              </div>
            </article>

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

          <!-- ── COLONNE DROITE ── -->
          <aside class="flex min-h-0 flex-col overflow-hidden">
            <!-- Cible eBay : la pièce que la query a cherchée. Toujours
                 affichée (mode-agnostic), pré-sélectionnée par défaut.
                 ~80 % des reviews valident la cible → un clic gagné. -->
            <section
              v-if="currentItem.target_candidate"
              class="mb-3 flex flex-col gap-1.5"
            >
              <p
                class="flex items-baseline justify-between font-mono text-[10px] uppercase tracking-wider"
                style="color: var(--gold-600);"
              >
                <span>Cible eBay</span>
                <span class="opacity-60">scrape par eurio_id</span>
              </p>
              <CandidateRow
                :candidate="currentItem.target_candidate"
                :index="0"
                badge="★"
                :focused="freeSearchCandidate?.eurio_id === currentItem.target_candidate.eurio_id"
                @focus="selectTarget"
              />
            </section>

            <!-- Mode AUTO : Top N + Dino + freeSearchCandidate banner -->
            <template v-if="mode === 'auto'">
              <div class="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">
                <p
                  class="flex items-baseline justify-between font-mono text-[10px] uppercase tracking-wider"
                  style="color: var(--ink-500);"
                >
                  <span>
                    <span style="color: var(--indigo-700);">Top {{ currentItem.candidates.length }}</span>
                    <span class="ml-1 opacity-60">candidats auto-name</span>
                  </span>
                  <span class="opacity-60">1 – 5</span>
                </p>

                <div class="flex flex-col gap-2">
                  <CandidateRow
                    v-for="(c, idx) in currentItem.candidates"
                    :key="c.eurio_id + idx"
                    :candidate="c"
                    :index="idx"
                    :focused="focusedCandidateIdx === idx && !freeSearchCandidate"
                    :style="{ animation: `fade-in 200ms ease-out ${idx * 30}ms backwards` }"
                    @focus="focusCandidate(idx)"
                  />
                </div>

                <DinoSuggestions
                  v-if="currentItem"
                  :review-id="currentItem.id"
                  variant="standard"
                  @select="onDinoSelect"
                />

                <article
                  v-if="freeSearchCandidate && freeSearchCandidate.eurio_id !== currentItem.target_candidate?.eurio_id"
                  class="mt-2 rounded-md border-2 border-dashed px-3 py-2"
                  :style="{
                    borderColor: 'var(--gold-600)',
                    background: 'color-mix(in srgb, var(--gold-600) 6%, var(--surface))',
                  }"
                >
                  <p class="font-mono text-[10px] uppercase tracking-wider" style="color: var(--gold-600);">
                    Sélection libre
                  </p>
                  <p class="mt-1 font-mono text-[12px]" style="color: var(--ink);">
                    {{ freeSearchCandidate.eurio_id }}
                  </p>
                  <p class="mt-0.5 text-[11px]" style="color: var(--ink-500);">
                    {{ freeSearchCandidate.label }}
                  </p>
                </article>

                <p
                  v-if="!currentItem.candidates.length"
                  class="rounded-md border-2 border-dashed px-4 py-6 text-center text-[12px]"
                  style="border-color: var(--surface-3); color: var(--ink-400);"
                >
                  Pas de candidat auto.<br />
                  Touche <kbd
                    class="mx-1 inline-block rounded px-1.5 py-0.5 font-mono text-[10px]"
                    style="background: var(--surface-1); border: 1px solid var(--surface-3);"
                  >F</kbd> pour la sélection libre.
                </p>
              </div>
            </template>

            <!-- Mode LIBRE : cascade pays/dénom/année + résultats inline -->
            <template v-else>
              <FreeSelectorPanel class="min-h-0 flex-1" @select="onSearchSelect" />
            </template>
          </aside>
      </div>

      <ReviewActionBar
        :face="face"
        :can-validate="!!focusedCandidate"
        :focused-eurio-id="focusedCandidate?.eurio_id ?? null"
        @face="setFace"
        @validate="validateCurrent"
        @reject="rejectCurrent"
        @skip="skipCurrent"
      />
    </section>

    <!-- ═══ Undo toast ═══ -->
    <Transition name="toast">
      <div
        v-if="undoToast"
        class="fixed bottom-20 left-1/2 z-20 -translate-x-1/2 inline-flex items-center gap-3 rounded-full border px-4 py-2 text-[12px] shadow-lg"
        style="border-color: var(--surface-3); background: var(--ink); color: var(--surface);"
      >
        <span>
          Action <strong>{{ undoToast.action }}</strong> effectuée
        </span>
        <button
          type="button"
          class="inline-flex items-center gap-1 rounded-md px-2 py-0.5 font-mono text-[11px] transition-colors"
          style="background: var(--surface); color: var(--ink);"
          @click="undoLast"
        >
          <Undo2 class="h-3 w-3" /> Annuler
        </button>
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

kbd {
  font-family: ui-monospace, SFMono-Regular, monospace;
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
