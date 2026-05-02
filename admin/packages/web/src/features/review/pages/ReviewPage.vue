<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Keyboard, Search, Undo2 } from 'lucide-vue-next'
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
import CoinSearchModal from '../components/CoinSearchModal.vue'

// ─── State ──────────────────────────────────────────────────────────────

const queue = ref<ReviewItem[]>([])
const currentIndex = ref(0)
const focusedCandidateIdx = ref<number | null>(null)
const freeSearchCandidate = ref<ReviewCandidate | null>(null)
const face = ref<ReviewFace>('obverse')
const stats = ref<ReviewStats | null>(null)
const showHelp = ref(false)
const searchOverlayOpen = ref(false)
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
  // Auto-focus le top-1 si score >= 0.5, sinon laisse l'humain choisir
  const top1 = currentItem.value?.candidates[0]
  focusedCandidateIdx.value = top1 && top1.score >= 0.5 ? 0 : null
  face.value = currentItem.value?.face_detected ?? 'obverse'
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

function openSearchOverlay() {
  // Chunk 4 : ouvre la modal /coins/search (non câblée pour l'instant)
  searchOverlayOpen.value = true
}

function closeSearchOverlay() {
  if (showHelp.value) {
    showHelp.value = false
    return
  }
  searchOverlayOpen.value = false
}

function onSearchSelect(entry: CoinSearchEntry) {
  // Promotion d'une entrée du sélecteur libre en candidat focusé.
  // Le ReviewCandidate synthétique sert l'action bar (validate ⏎).
  freeSearchCandidate.value = {
    eurio_id: entry.eurio_id,
    score: 1.0, // sélection humaine
    label: entry.label,
    country: entry.country,
    denomination: entry.denomination,
    year: entry.year,
    canonical_thumb_url: entry.canonical_thumb_url,
  }
  focusedCandidateIdx.value = null
  searchOverlayOpen.value = false
}


// ─── Keyboard ───────────────────────────────────────────────────────────

const keyboardEnabled = computed(() => !showHelp.value && !searchOverlayOpen.value)

useReviewKeybinds(keyboardEnabled, {
  onCandidateFocus: focusCandidate,
  onValidate: validateCurrent,
  onReject: rejectCurrent,
  onSkip: skipCurrent,
  onOpenSearch: openSearchOverlay,
  onCloseOverlay: closeSearchOverlay,
  onSetFace: setFace,
})
</script>

<template>
  <div class="flex h-full flex-col">
    <!-- ═══ Top bar discrète ═══ -->
    <header
      class="flex flex-wrap items-center justify-between gap-4 border-b px-8 py-3"
      style="border-color: var(--surface-3); background: var(--surface);"
    >
      <div>
        <h1
          class="font-display text-lg italic font-semibold"
          style="color: var(--indigo-700);"
        >
          Review queue
        </h1>
        <p class="mt-0.5 text-xs" style="color: var(--ink-500);">
          Résolution humaine des images non auto-matchées
        </p>
      </div>

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

      <div class="flex items-center gap-2">
        <button
          type="button"
          class="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px] transition-colors"
          style="border-color: var(--surface-3); color: var(--ink-500); background: var(--surface-1);"
          :title="'Sélecteur libre · F'"
          @click="openSearchOverlay"
        >
          <Search class="h-3 w-3" />
          Sélecteur libre
          <span class="ml-1 font-mono text-[9px] uppercase tracking-wider opacity-70">F</span>
        </button>
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
    </header>

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
      <div class="flex-1 overflow-y-auto px-8 py-6">
        <div class="grid gap-6 lg:grid-cols-[2fr_1fr]">
          <!-- ── COLONNE GAUCHE : Crop + canonique split A/B + meta ── -->
          <div class="flex flex-col gap-4">
            <SplitCompare
              :crop-url="currentItem.crop_url"
              :canonical-url="focusedCandidate?.canonical_thumb_url ?? null"
              :bbox="currentItem.bbox"
            />

            <!-- Métadonnées listing -->
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
          </div>

          <!-- ── COLONNE DROITE : Top-5 candidats ── -->
          <aside class="flex flex-col gap-3">
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

            <!-- Free search candidate (set via Chunk 4 modal) -->
            <article
              v-if="freeSearchCandidate"
              class="mt-2 rounded-md border-2 border-dashed px-3 py-2"
              :style="{
                borderColor: 'var(--gold-600)',
                background: 'color-mix(in srgb, var(--gold-600) 6%, var(--surface))',
              }"
            >
              <p class="font-mono text-[10px] uppercase tracking-wider" style="color: var(--gold-600);">
                Sélecteur libre
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
              >F</kbd> pour le sélecteur libre.
            </p>
          </aside>
        </div>
      </div>

      <!-- ═══ Bottom action bar ═══ -->
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
          <dd style="color: var(--ink-500);">Sélecteur libre (overlay)</dd>
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

    <!-- ═══ Coin search modal (sélecteur libre) ═══ -->
    <CoinSearchModal
      :open="searchOverlayOpen"
      @close="searchOverlayOpen = false"
      @select="onSearchSelect"
    />
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
</style>
