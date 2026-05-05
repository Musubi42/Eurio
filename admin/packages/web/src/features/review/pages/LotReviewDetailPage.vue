<script setup lang="ts">
// Page full-page review d'un lot — Specimen Plate (Phase 2 Chunk 5).
//
// Stages :
//   1+2. Examination plate : raw + overlay SVG des cercles détectés/rejetés
//        (toggle D), tags numérotés liés aux crop cards.
//   3. Isolates : crop cards avec actions (assign / reject / skip), bulk
//      via checkbox + sub-footer indigo, raccourcis clavier alignés single.
//
// Nav prev/next entre listings (← / →), validate→next chain avec bouton
// stop. La grille `/review?mode=lot` est l'entrée, cette page est l'écran
// de travail.
//
// Cf. docs/sources-refacto/prototype-review-lot-debug.html (proto)
// + docs/sources-refacto/lot-review-kickoff.md.

import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft, ArrowRight, Check, CheckCircle2, CheckSquare, ChevronDown,
  Keyboard, Loader2, RotateCcw, Search, SkipForward, Square,
  Trash2, X,
} from 'lucide-vue-next'
import {
  decideLot, fetchLot, LotReviewError,
  type LotAssignment, type LotDetail, type LotRejectReason,
} from '../composables/useLotReview'
import { useLotReviewKeybinds } from '../composables/useLotReviewKeybinds'
import CoinSearchModal from '../components/CoinSearchModal.vue'
import type { CoinSearchEntry } from '../composables/useCoinsSearch'

const route = useRoute()
const router = useRouter()

// ─── State ─────────────────────────────────────────────────────────────

const detail = ref<LotDetail | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const showHelp = ref(false)
const showOverlay = ref(true)         // toggle Stage 2 cercles (D)
const autoAdvance = ref(true)          // validate→next chain
const submitting = ref(false)
const lastDecisionToast = ref<{ done: number; rejected: number; skipped: number } | null>(null)

// Decisions per asset_id, accumulé localement, envoyé au "Valider listing".
type PendingDecision =
  | { kind: 'assign'; eurio_id: string; label: string; face: 'obverse' | 'reverse' | 'unknown' }
  | { kind: 'reject'; reason: LotRejectReason }
  | { kind: 'skip' }
const decisions = ref<Record<string, PendingDecision>>({})

// Bulk selection.
const selected = ref<Set<string>>(new Set())
const bulkMode = computed(() => selected.value.size > 0)
const bulkRejectOpen = ref(false)

// Search modal target (single ou bulk).
type SearchTarget = { kind: 'single'; assetId: string } | { kind: 'bulk' } | null
const searchTarget = ref<SearchTarget>(null)

// Active raw (image index) — défaut première image.
const activeRawIndex = ref(0)

// Active crop (cursor clavier) — index dans `actionableCrops`.
const activeCropIndex = ref(0)
const cropRowRefs = ref<Record<string, HTMLElement | null>>({})

const REJECT_REASONS: { value: LotRejectReason; label: string }[] = [
  { value: 'not_a_coin', label: 'Pas une pièce' },
  { value: 'out_of_scope', label: 'Hors-scope' },
  { value: 'duplicate_in_listing', label: 'Doublon dans le listing' },
  { value: 'unreadable', label: 'Illisible' },
  { value: 'other', label: 'Autre' },
]

// ─── Derived ───────────────────────────────────────────────────────────

const listingKey = computed<string>(() => {
  const k = route.params.listing_key
  return Array.isArray(k) ? k[0] : (k ?? '')
})

const activeImage = computed(() => detail.value?.images[activeRawIndex.value] ?? null)

// Tous les crops du listing, avec lien vers leur source_image (pour image_index).
const allCrops = computed(() =>
  detail.value?.images.flatMap((im) => im.crops.map((c) => ({ image: im, crop: c }))) ?? [],
)

// Crops actionnables = ceux avec un review_id (en queue 'lot' open).
const actionableCrops = computed(() =>
  allCrops.value.filter(({ crop }) => crop.review_id),
)

const decidedCount = computed(() => Object.keys(decisions.value).length)
const totalActionable = computed(() => actionableCrops.value.length)
const allDecided = computed(
  () => totalActionable.value > 0 && decidedCount.value === totalActionable.value,
)

const activeCrop = computed(() => actionableCrops.value[activeCropIndex.value] ?? null)
const activeAssetId = computed(() => activeCrop.value?.crop.asset_id ?? null)

// Mappe crop_index ↔ asset_id pour l'image active (lien overlay → card).
const assetIdByCropIndex = computed(() => {
  const m: Record<number, string> = {}
  if (activeImage.value) {
    for (const c of activeImage.value.crops) m[c.crop_index] = c.asset_id
  }
  return m
})

// Numéro de tag (1-based) dans l'image active, indexé par asset_id.
const tagNumberByAssetId = computed(() => {
  const m: Record<string, number> = {}
  if (activeImage.value) {
    activeImage.value.crops.forEach((c, idx) => { m[c.asset_id] = idx + 1 })
  }
  return m
})

// SVG viewBox = dimensions natives du raw (les détections sont dans cet espace).
const overlayViewBox = computed(() => {
  const im = activeImage.value
  if (!im || !im.raw_width || !im.raw_height) return '0 0 1000 750'
  return `0 0 ${im.raw_width} ${im.raw_height}`
})

// ─── Loaders ───────────────────────────────────────────────────────────

async function load(key: string) {
  loading.value = true
  error.value = null
  detail.value = null
  decisions.value = {}
  selected.value = new Set()
  bulkRejectOpen.value = false
  activeCropIndex.value = 0
  activeRawIndex.value = 0
  showHelp.value = false
  searchTarget.value = null
  try {
    detail.value = await fetchLot(key)
  } catch (err) {
    error.value = err instanceof LotReviewError ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

watch(listingKey, (k) => { if (k) void load(k) }, { immediate: true })
onMounted(() => { if (listingKey.value) void load(listingKey.value) })

// ─── Decision helpers ──────────────────────────────────────────────────

function assignToCandidate(assetId: string, eurio_id: string, label: string) {
  decisions.value = {
    ...decisions.value,
    [assetId]: { kind: 'assign', eurio_id, label, face: 'obverse' },
  }
}

function rejectCrop(assetId: string, reason: LotRejectReason) {
  decisions.value = { ...decisions.value, [assetId]: { kind: 'reject', reason } }
}

function skipCrop(assetId: string) {
  decisions.value = { ...decisions.value, [assetId]: { kind: 'skip' } }
}

function clearDecision(assetId: string) {
  const next = { ...decisions.value }
  delete next[assetId]
  decisions.value = next
}

function openSearchFor(assetId: string) {
  searchTarget.value = { kind: 'single', assetId }
}

function openBulkSearch() {
  searchTarget.value = { kind: 'bulk' }
}

function onSearchSelect(entry: CoinSearchEntry) {
  const target = searchTarget.value
  if (!target) return
  const next = { ...decisions.value }
  const apply = (id: string) => {
    next[id] = { kind: 'assign', eurio_id: entry.eurio_id, label: entry.label, face: 'obverse' }
  }
  if (target.kind === 'single') apply(target.assetId)
  else { for (const id of selected.value) apply(id); selected.value = new Set() }
  decisions.value = next
  searchTarget.value = null
}

// ─── Bulk selection ────────────────────────────────────────────────────

function toggleSelected(assetId: string) {
  const next = new Set(selected.value)
  if (next.has(assetId)) next.delete(assetId); else next.add(assetId)
  selected.value = next
}

function clearSelection() {
  selected.value = new Set()
  bulkRejectOpen.value = false
}

function bulkReject(reason: LotRejectReason) {
  const next = { ...decisions.value }
  for (const id of selected.value) next[id] = { kind: 'reject', reason }
  decisions.value = next
  bulkRejectOpen.value = false
  selected.value = new Set()
}

function bulkSkip() {
  const next = { ...decisions.value }
  for (const id of selected.value) next[id] = { kind: 'skip' }
  decisions.value = next
  selected.value = new Set()
}

const allActionableSelected = computed(() => {
  if (!totalActionable.value) return false
  return actionableCrops.value.every(({ crop }) => selected.value.has(crop.asset_id))
})

function toggleAllSelection() {
  if (allActionableSelected.value) clearSelection()
  else selected.value = new Set(actionableCrops.value.map(({ crop }) => crop.asset_id))
}

// ─── Active crop nav ───────────────────────────────────────────────────

function setActiveIndex(idx: number) {
  if (!actionableCrops.value.length) return
  const max = actionableCrops.value.length - 1
  const clamped = Math.max(0, Math.min(max, idx))
  activeCropIndex.value = clamped
  // Activate the matching raw (image_index) for visual sync with overlay.
  const target = actionableCrops.value[clamped]
  if (target && detail.value) {
    const imIdx = detail.value.images.findIndex((im) => im.source_image_id === target.image.source_image_id)
    if (imIdx >= 0) activeRawIndex.value = imIdx
  }
  void nextTick(() => {
    const id = actionableCrops.value[clamped]?.crop.asset_id
    if (!id) return
    cropRowRefs.value[id]?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  })
}

function nextCrop() { setActiveIndex(activeCropIndex.value + 1) }
function prevCrop() { setActiveIndex(activeCropIndex.value - 1) }

function setRowRef(assetId: string, el: Element | any) {
  cropRowRefs.value[assetId] = el instanceof HTMLElement ? el : null
}

// ─── Submit + chain ────────────────────────────────────────────────────

async function submit() {
  if (!detail.value || !allDecided.value || submitting.value) return
  submitting.value = true
  try {
    const assignments: LotAssignment[] = Object.entries(decisions.value).map(([asset_id, d]) => {
      if (d.kind === 'assign') return { asset_id, eurio_id: d.eurio_id, face: d.face }
      if (d.kind === 'reject') return { asset_id, reject_reason: d.reason }
      return { asset_id, skip: true }
    })
    const res = await decideLot(detail.value.listing_key, assignments)
    lastDecisionToast.value = { done: res.done, rejected: res.rejected, skipped: res.skipped }
    setTimeout(() => { lastDecisionToast.value = null }, 4500)
    if (autoAdvance.value && detail.value.next_listing_key) {
      void router.replace(`/review/lot/${encodeURIComponent(detail.value.next_listing_key)}`)
    } else {
      // No more lots, go back to grid.
      void router.replace('/review?mode=lot')
    }
  } catch (err) {
    error.value = err instanceof LotReviewError ? err.message : String(err)
  } finally {
    submitting.value = false
  }
}

function gotoPrev() {
  if (detail.value?.prev_listing_key) {
    void router.replace(`/review/lot/${encodeURIComponent(detail.value.prev_listing_key)}`)
  }
}
function gotoNext() {
  if (detail.value?.next_listing_key) {
    void router.replace(`/review/lot/${encodeURIComponent(detail.value.next_listing_key)}`)
  }
}
function closePage() {
  void router.push('/review?mode=lot')
}

// ─── Keyboard ──────────────────────────────────────────────────────────

function kbAssignCandidate(idx: number) {
  const a = activeCrop.value
  if (!a) return
  const cand = a.crop.candidate_eurio_ids[idx]
  if (!cand) return
  assignToCandidate(a.crop.asset_id, cand.eurio_id, cand.label)
}
function kbRejectActive() {
  const id = activeAssetId.value
  if (!id) return
  rejectCrop(id, 'other')
}
function kbSkipActive() {
  const id = activeAssetId.value
  if (!id) return
  skipCrop(id)
}
function kbOpenSearchActive() {
  const id = activeAssetId.value
  if (!id) return
  openSearchFor(id)
}
function kbSetFaceActive(face: 'obverse' | 'reverse' | 'unknown') {
  const id = activeAssetId.value
  if (!id) return
  const cur = decisions.value[id]
  if (!cur || cur.kind !== 'assign') return
  decisions.value = { ...decisions.value, [id]: { ...cur, face } }
}
function kbSubmit() { if (allDecided.value && !submitting.value) void submit() }
function toggleHelp() { showHelp.value = !showHelp.value }
function toggleOverlay() { showOverlay.value = !showOverlay.value }

function closeOverlay() {
  if (showHelp.value) { showHelp.value = false; return }
  if (searchTarget.value) { searchTarget.value = null; return }
  if (bulkRejectOpen.value) { bulkRejectOpen.value = false; return }
  if (bulkMode.value) { clearSelection(); return }
  closePage()
}

const keyboardEnabled = computed(
  () => !showHelp.value && searchTarget.value === null,
)

useLotReviewKeybinds(keyboardEnabled, {
  onAssignCandidate: kbAssignCandidate,
  onSubmit: kbSubmit,
  onRejectActive: kbRejectActive,
  onSkipActive: kbSkipActive,
  onOpenSearch: kbOpenSearchActive,
  onSetFaceActive: kbSetFaceActive,
  onNextCrop: nextCrop,
  onPrevCrop: prevCrop,
  onToggleHelp: toggleHelp,
  onCloseOverlay: closeOverlay,
})

// Additional global keybinds beyond the composable (D, ←, →).
function onKeydown(e: KeyboardEvent) {
  if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
  if (e.metaKey || e.ctrlKey || e.altKey) return
  if (showHelp.value || searchTarget.value) return
  if (e.key === 'd' || e.key === 'D') { toggleOverlay(); e.preventDefault() }
  else if (e.key === 'ArrowLeft' && !actionableCrops.value.length) {
    // Don't shadow if J/K context: arrows already used by composable for crop nav.
    gotoPrev(); e.preventDefault()
  } else if (e.key === 'ArrowRight' && !actionableCrops.value.length) {
    gotoNext(); e.preventDefault()
  }
}
onMounted(() => window.addEventListener('keydown', onKeydown))
import { onUnmounted } from 'vue'
onUnmounted(() => window.removeEventListener('keydown', onKeydown))

// ─── Visual helpers ────────────────────────────────────────────────────

function cropDecisionLabel(assetId: string): string | null {
  const d = decisions.value[assetId]
  if (!d) return null
  if (d.kind === 'assign') {
    const f = d.face === 'obverse' ? 'O' : d.face === 'reverse' ? 'V' : 'U'
    return `→ ${d.label} · ${f}`
  }
  if (d.kind === 'reject') return `rejeté · ${d.reason}`
  return 'reporté'
}
function cropDecisionTone(assetId: string): string {
  const d = decisions.value[assetId]
  if (!d) return 'var(--ink-400)'
  if (d.kind === 'assign') return 'var(--success)'
  if (d.kind === 'reject') return 'var(--danger)'
  return 'var(--ink-500)'
}
function isAssignedTo(assetId: string, eurio_id: string): boolean {
  const d = decisions.value[assetId]
  return !!d && d.kind === 'assign' && d.eurio_id === eurio_id
}

function detectionTagPos(det: { cx: number; cy: number; r: number }) {
  // Place tag in the top-right of the circle (offset by ~r/√2).
  const off = det.r * 0.7
  return { x: det.cx + off, y: det.cy - off }
}
</script>

<template>
  <div class="flex h-full flex-col" style="background: var(--surface);">

    <!-- ═══ HEADER ═══ -->
    <header
      class="flex flex-wrap items-end justify-between gap-4 border-b px-8 py-4"
      style="border-color: var(--surface-3); background: var(--surface);"
    >
      <div class="min-w-0 flex-1">
        <div class="flex items-baseline gap-3 flex-wrap">
          <span
            class="font-mono text-[10px] uppercase tracking-[0.18em]"
            style="color: var(--gold-600);"
          >Case №</span>
          <code class="font-mono text-[12px]" style="color: var(--ink-700);">{{ listingKey }}</code>
          <span v-if="detail" class="inline-flex items-baseline gap-1.5 flex-wrap">
            <span class="tag tag--gold" v-if="detail.is_lot_suspected">⌗ lot suspected</span>
            <span class="tag tag--gold" v-else-if="detail.is_multi_crop_single">⌗ multi-crop</span>
            <span class="tag tag--indigo" v-if="detail.target_eurio_id">→ {{ detail.target_eurio_id }}</span>
            <span class="tag">src · {{ detail.source }}</span>
            <span class="tag" v-if="detail.listing_price !== null">€&nbsp;{{ detail.listing_price.toFixed(2) }}</span>
          </span>
        </div>
        <h1
          v-if="detail"
          class="mt-1 font-display text-[28px] italic font-semibold leading-tight"
          style="color: var(--ink);"
        >
          <span style="color: var(--gold-600);">«</span>
          {{ detail.listing_title ?? '— sans titre —' }}
          <span style="color: var(--gold-600);">»</span>
        </h1>
      </div>

      <nav class="flex items-center gap-1.5">
        <button class="nav-btn" :disabled="!detail?.prev_listing_key" title="Listing précédent (←)" @click="gotoPrev">
          <ArrowLeft class="h-4 w-4" />
        </button>
        <label
          class="inline-flex items-center gap-1.5 px-2.5 py-1.5 border text-[11px] cursor-pointer select-none"
          :style="{
            borderColor: autoAdvance ? 'var(--gold-600)' : 'var(--surface-3)',
            color: autoAdvance ? 'var(--gold-600)' : 'var(--ink-500)',
            background: autoAdvance ? 'color-mix(in srgb, var(--gold-600) 8%, var(--surface))' : 'var(--surface-1)',
          }"
          title="Auto-advance after validate (chain)"
        >
          <input v-model="autoAdvance" type="checkbox" class="hidden" />
          <span class="font-mono">⌘</span>
          chain
        </label>
        <button class="nav-btn nav-btn--text" title="Aide (?)" @click="toggleHelp">
          <Keyboard class="h-3.5 w-3.5" />
          <kbd>?</kbd>
        </button>
        <button class="nav-btn" :disabled="!detail?.next_listing_key" title="Listing suivant (→)" @click="gotoNext">
          <ArrowRight class="h-4 w-4" />
        </button>
        <button class="nav-btn ml-2" title="Fermer (Esc)" @click="closePage">
          <X class="h-4 w-4" />
        </button>
      </nav>
    </header>

    <!-- Loading / error -->
    <div v-if="loading" class="flex flex-1 items-center justify-center gap-2 text-sm" style="color: var(--ink-400);">
      <Loader2 class="h-4 w-4 animate-spin" /> Chargement…
    </div>
    <div
      v-else-if="error"
      class="m-8 rounded-lg border px-4 py-3 text-sm"
      style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 4%, var(--surface)); color: var(--danger);"
    >
      {{ error }}
    </div>

    <!-- ═══ BODY (2 cols) ═══ -->
    <div v-else-if="detail" class="grid flex-1 overflow-hidden" style="grid-template-columns: 1fr 480px;">

      <!-- ─── EXAMINATION PLATE (Stage 1+2) ─── -->
      <section class="flex flex-col gap-3 overflow-y-auto border-r px-7 py-5" style="border-color: var(--surface-3);">
        <div class="flex items-baseline justify-between gap-4">
          <div class="flex items-center gap-2.5">
            <span class="kicker-line"></span>
            <span class="kicker" style="color: var(--gold-600);">Examination plate</span>
            <span class="font-mono text-[10px]" style="color: var(--ink-400);">
              img {{ activeRawIndex + 1 }} / {{ detail.images.length }}
            </span>
          </div>
          <div class="flex items-center gap-3">
            <label class="inline-flex items-center gap-1.5 cursor-pointer text-[11px]" style="color: var(--ink-500);">
              <input v-model="showOverlay" type="checkbox" class="hidden" />
              <span class="switch" :class="{ on: showOverlay }"></span>
              <span>Détections</span>
              <kbd>D</kbd>
            </label>
          </div>
        </div>

        <!-- Raw selector strip -->
        <div v-if="detail.images.length > 0" class="flex gap-1.5 overflow-x-auto pb-1">
          <button
            v-for="(im, idx) in detail.images"
            :key="im.source_image_id"
            class="raw-thumb"
            :class="{ active: idx === activeRawIndex }"
            :title="`img ${im.image_index ?? idx + 1} · ${im.crops.length} crop${im.crops.length > 1 ? 's' : ''}`"
            @click="activeRawIndex = idx"
          >
            <img :src="im.raw_url" :alt="`img ${idx + 1}`" loading="lazy" />
            <span class="tag-overlay tag-overlay--tl">{{ idx + 1 }}</span>
            <span class="tag-overlay tag-overlay--br">{{ im.crops.length }} cr.</span>
          </button>
        </div>

        <!-- Plate frame: raw + SVG overlay -->
        <div
          v-if="activeImage"
          class="relative w-full overflow-hidden border"
          :style="{ borderColor: 'var(--surface-3)', background: 'var(--surface-2)', aspectRatio: activeImage.raw_width && activeImage.raw_height ? `${activeImage.raw_width} / ${activeImage.raw_height}` : '4 / 3' }"
        >
          <img
            :src="activeImage.raw_url"
            :alt="`raw ${activeRawIndex + 1}`"
            class="absolute inset-0 h-full w-full object-contain"
          />
          <svg
            class="absolute inset-0 h-full w-full pointer-events-none"
            :viewBox="overlayViewBox"
            preserveAspectRatio="xMidYMid meet"
            :style="{ opacity: showOverlay ? 1 : 0, transition: 'opacity 200ms ease' }"
          >
            <!-- Detected (accepted) circles -->
            <g>
              <circle
                v-for="(det, i) in activeImage.detections.filter(d => d.accepted)"
                :key="`a-${i}`"
                :cx="det.cx" :cy="det.cy" :r="det.r"
                fill="none"
                :stroke="det.crop_index !== null && assetIdByCropIndex[det.crop_index] === activeAssetId ? 'var(--gold-500)' : 'var(--gold-600)'"
                :stroke-width="det.crop_index !== null && assetIdByCropIndex[det.crop_index] === activeAssetId ? 6 : 3"
              />
              <!-- Tag badges (number = crop_index + 1) -->
              <g v-for="(det, i) in activeImage.detections.filter(d => d.accepted)" :key="`tag-${i}`">
                <circle
                  :cx="detectionTagPos(det).x"
                  :cy="detectionTagPos(det).y"
                  r="22" fill="var(--ink)" stroke="var(--surface)" stroke-width="3"
                />
                <text
                  :x="detectionTagPos(det).x" :y="detectionTagPos(det).y + 1"
                  text-anchor="middle" dominant-baseline="central"
                  font-family="JetBrains Mono" font-size="20" font-weight="600"
                  fill="var(--surface)"
                >{{ (det.crop_index ?? 0) + 1 }}</text>
              </g>
            </g>
            <!-- Rejected circles (red dashed) -->
            <g>
              <circle
                v-for="(det, i) in activeImage.detections.filter(d => !d.accepted)"
                :key="`r-${i}`"
                :cx="det.cx" :cy="det.cy" :r="det.r"
                fill="none" stroke="var(--danger)" stroke-width="2"
                stroke-dasharray="8 6" opacity="0.7"
              />
              <text
                v-for="(det, i) in activeImage.detections.filter(d => !d.accepted)"
                :key="`rt-${i}`"
                :x="det.cx" :y="det.cy + 4" text-anchor="middle"
                font-family="JetBrains Mono" font-size="14"
                fill="var(--danger)" opacity="0.8"
              >{{ det.reject_reason }}</text>
            </g>
          </svg>
        </div>

        <!-- Plate footnote -->
        <div v-if="activeImage" class="flex flex-wrap items-baseline gap-3 font-mono text-[10px]" style="color: var(--ink-500);">
          <span v-if="activeImage.raw_width && activeImage.raw_height">
            <strong style="color: var(--ink-700); font-weight: 500;">{{ activeImage.raw_width }} × {{ activeImage.raw_height }}</strong>
          </span>
          <span style="color: var(--surface-3);">·</span>
          <span>
            <strong style="color: var(--ink-700); font-weight: 500;">{{ activeImage.detections.length }}</strong>
            cercles ·
            <span style="color: var(--success);">{{ activeImage.detections.filter(d => d.accepted).length }} retenus</span>
            <template v-if="activeImage.detections.filter(d => !d.accepted).length">
              · <span style="color: var(--danger);">{{ activeImage.detections.filter(d => !d.accepted).length }} écartés</span>
            </template>
          </span>
        </div>
      </section>

      <!-- ─── ISOLATES (Stage 3) ─── -->
      <section class="flex flex-col overflow-hidden" style="background: var(--surface-1);">
        <div class="flex items-baseline justify-between gap-3 px-6 py-4 border-b" style="border-color: var(--surface-3);">
          <div>
            <span class="kicker" style="color: var(--gold-600);">Isolates</span>
            <span class="ml-2 font-mono text-[10px]" style="color: var(--ink-400);">
              {{ totalActionable }} specimen{{ totalActionable > 1 ? 's' : '' }} à résoudre
            </span>
          </div>
          <div class="flex items-center gap-2">
            <button
              v-if="totalActionable > 0"
              class="inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 font-mono text-[10px] transition-colors"
              :style="{
                borderColor: 'var(--surface-3)',
                background: allActionableSelected ? 'color-mix(in srgb, var(--indigo-700) 8%, var(--surface-1))' : 'var(--surface-1)',
                color: allActionableSelected ? 'var(--indigo-700)' : 'var(--ink-500)',
              }"
              :title="allActionableSelected ? 'Tout désélectionner' : 'Tout sélectionner'"
              @click="toggleAllSelection"
            >
              <CheckSquare v-if="allActionableSelected" class="h-3 w-3" />
              <Square v-else class="h-3 w-3" />
              {{ allActionableSelected ? 'tout désélec.' : 'tout sélec.' }}
            </button>
            <span class="font-mono text-[10px]" style="color: var(--ink-500);">
              <strong style="color: var(--gold-600);">{{ decidedCount }}</strong> / {{ totalActionable }}
            </span>
          </div>
        </div>

        <ul class="flex-1 overflow-y-auto p-3 space-y-2">
          <li v-if="!actionableCrops.length" class="rounded-md border-2 border-dashed px-4 py-8 text-center text-sm" style="border-color: var(--surface-3); color: var(--ink-400);">
            Aucun crop en review pour ce listing.
          </li>

          <li
            v-for="({ crop, image }, idx) in actionableCrops"
            :key="crop.asset_id"
            :ref="(el) => setRowRef(crop.asset_id, el)"
            class="relative flex gap-3 rounded-md border px-3 py-2 transition-shadow cursor-pointer"
            :style="{
              borderColor: selected.has(crop.asset_id)
                ? 'var(--indigo-700)'
                : decisions[crop.asset_id] ? cropDecisionTone(crop.asset_id) : 'var(--surface-3)',
              background: selected.has(crop.asset_id)
                ? 'color-mix(in srgb, var(--indigo-700) 5%, var(--surface))'
                : decisions[crop.asset_id]
                  ? `color-mix(in srgb, ${cropDecisionTone(crop.asset_id)} 5%, var(--surface))`
                  : 'var(--surface)',
              boxShadow: idx === activeCropIndex ? '0 0 0 2px var(--gold-600)' : 'none',
            }"
            @click="setActiveIndex(idx)"
          >
            <!-- Crop tag (number, top-left) -->
            <div
              class="absolute -top-2 -left-2 flex h-6 w-6 items-center justify-center rounded-full font-mono text-[11px] font-semibold"
              :style="{
                background: idx === activeCropIndex || decisions[crop.asset_id]?.kind === 'assign'
                  ? 'var(--gold-600)'
                  : decisions[crop.asset_id]?.kind === 'reject'
                    ? 'var(--danger)'
                    : 'var(--ink)',
                color: 'var(--surface)',
              }"
            >{{ tagNumberByAssetId[crop.asset_id] ?? idx + 1 }}</div>

            <!-- Bulk checkbox (top-right) -->
            <button
              type="button"
              class="absolute top-2 right-2 flex h-4 w-4 items-center justify-center rounded border transition-colors"
              :style="{
                borderColor: selected.has(crop.asset_id) ? 'var(--indigo-700)' : 'var(--surface-3)',
                background: selected.has(crop.asset_id) ? 'var(--indigo-700)' : 'var(--surface-1)',
                color: 'var(--surface)',
              }"
              :title="selected.has(crop.asset_id) ? 'Désélectionner' : 'Sélectionner'"
              @click.stop="toggleSelected(crop.asset_id)"
            >
              <Check v-if="selected.has(crop.asset_id)" class="h-3 w-3" />
            </button>

            <!-- Crop thumb -->
            <div class="h-16 w-16 shrink-0 overflow-hidden rounded-full border" style="border-color: var(--surface-3); background: var(--surface-1);">
              <img :src="crop.crop_url" :alt="`crop ${crop.crop_index}`" class="h-full w-full object-cover" loading="lazy" />
            </div>

            <!-- Crop body -->
            <div class="flex min-w-0 flex-1 flex-col gap-1.5">
              <div class="flex items-baseline justify-between pr-6">
                <p class="font-mono text-[10px]" style="color: var(--ink-500);">
                  img {{ image.image_index ?? '?' }} · crop {{ crop.crop_index }}
                </p>
                <p
                  v-if="cropDecisionLabel(crop.asset_id)"
                  class="font-mono text-[10px]"
                  :style="{ color: cropDecisionTone(crop.asset_id) }"
                >
                  {{ cropDecisionLabel(crop.asset_id) }}
                </p>
              </div>

              <!-- Top candidates -->
              <div v-if="crop.candidate_eurio_ids.length" class="flex flex-wrap gap-1">
                <button
                  v-for="cand in crop.candidate_eurio_ids.slice(0, 3)"
                  :key="cand.eurio_id"
                  type="button"
                  class="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-[10px] transition-colors"
                  :style="{
                    borderColor: isAssignedTo(crop.asset_id, cand.eurio_id) ? 'var(--success)' : 'var(--surface-3)',
                    color: isAssignedTo(crop.asset_id, cand.eurio_id) ? 'var(--success)' : 'var(--ink-700)',
                    background: 'var(--surface-1)',
                  }"
                  :title="cand.label"
                  @click.stop="assignToCandidate(crop.asset_id, cand.eurio_id, cand.label)"
                >
                  {{ cand.eurio_id }}
                  <span style="color: var(--ink-400);">{{ (cand.score * 100).toFixed(0) }}%</span>
                </button>
              </div>

              <!-- Actions -->
              <div class="flex flex-wrap items-center gap-1.5">
                <button
                  type="button"
                  class="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 font-mono text-[10px] transition-colors"
                  style="border-color: var(--surface-3); color: var(--indigo-700); background: var(--surface);"
                  @click.stop="openSearchFor(crop.asset_id)"
                >
                  <Search class="h-2.5 w-2.5" /> Assigner…
                </button>
                <details class="relative" @click.stop>
                  <summary
                    class="inline-flex cursor-pointer items-center gap-1 rounded-md border px-2 py-0.5 font-mono text-[10px] list-none"
                    style="border-color: var(--surface-3); color: var(--danger); background: var(--surface);"
                  >
                    <Trash2 class="h-2.5 w-2.5" /> Rejeter
                    <ChevronDown class="h-2.5 w-2.5 opacity-60" />
                  </summary>
                  <div
                    class="absolute right-0 z-10 mt-1 flex flex-col rounded-md border shadow-lg"
                    style="border-color: var(--surface-3); background: var(--surface); min-width: 180px;"
                  >
                    <button
                      v-for="r in REJECT_REASONS"
                      :key="r.value"
                      type="button"
                      class="px-3 py-1.5 text-left text-[11px] transition-colors"
                      style="color: var(--ink-700);"
                      @mouseenter="(e) => ((e.currentTarget as HTMLElement).style.background = 'var(--surface-1)')"
                      @mouseleave="(e) => ((e.currentTarget as HTMLElement).style.background = 'transparent')"
                      @click="(e) => { rejectCrop(crop.asset_id, r.value); ((e.currentTarget as HTMLElement).closest('details') as HTMLDetailsElement).open = false }"
                    >
                      {{ r.label }}
                    </button>
                  </div>
                </details>
                <button
                  type="button"
                  class="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 font-mono text-[10px] transition-colors"
                  style="border-color: var(--surface-3); color: var(--ink-500); background: var(--surface);"
                  @click.stop="skipCrop(crop.asset_id)"
                >
                  <SkipForward class="h-2.5 w-2.5" /> Skip
                </button>
                <button
                  v-if="decisions[crop.asset_id]"
                  type="button"
                  class="inline-flex items-center gap-1 rounded-md px-2 py-0.5 font-mono text-[10px] transition-colors"
                  style="color: var(--ink-400);"
                  title="Annuler la décision"
                  @click.stop="clearDecision(crop.asset_id)"
                >
                  <RotateCcw class="h-2.5 w-2.5" />
                </button>
              </div>
            </div>
          </li>
        </ul>

        <!-- Bulk sub-footer -->
        <Transition name="bulk">
          <div
            v-if="bulkMode"
            class="flex flex-wrap items-center justify-between gap-3 border-t px-5 py-2.5"
            style="
              border-color: var(--indigo-700);
              background: color-mix(in srgb, var(--indigo-700) 6%, var(--surface));
            "
          >
            <p class="font-mono text-[11px]" style="color: var(--indigo-700);">
              <strong>{{ selected.size }}</strong>
              <span class="ml-1 uppercase tracking-wider opacity-80">crop{{ selected.size > 1 ? 's' : '' }} sélectionné{{ selected.size > 1 ? 's' : '' }}</span>
            </p>
            <div class="flex flex-wrap items-center gap-1.5">
              <button class="bulk-btn" style="border-color: var(--indigo-700); color: var(--indigo-700);" @click="openBulkSearch">
                <Search class="h-3 w-3" /> Assigner…
              </button>
              <details class="relative" :open="bulkRejectOpen" @toggle="(e) => (bulkRejectOpen = (e.currentTarget as HTMLDetailsElement).open)">
                <summary class="bulk-btn" style="border-color: var(--danger); color: var(--danger);">
                  <Trash2 class="h-3 w-3" /> Rejeter <ChevronDown class="h-3 w-3 opacity-60" />
                </summary>
                <div
                  class="absolute right-0 bottom-full z-10 mb-1 flex flex-col rounded-md border shadow-lg"
                  style="border-color: var(--surface-3); background: var(--surface); min-width: 180px;"
                >
                  <button
                    v-for="r in REJECT_REASONS" :key="r.value"
                    type="button"
                    class="px-3 py-1.5 text-left text-[11px]"
                    style="color: var(--ink-700);"
                    @mouseenter="(e) => ((e.currentTarget as HTMLElement).style.background = 'var(--surface-1)')"
                    @mouseleave="(e) => ((e.currentTarget as HTMLElement).style.background = 'transparent')"
                    @click="bulkReject(r.value)"
                  >{{ r.label }}</button>
                </div>
              </details>
              <button class="bulk-btn" style="border-color: var(--surface-3); color: var(--ink-700);" @click="bulkSkip">
                <SkipForward class="h-3 w-3" /> Skip
              </button>
              <button class="bulk-btn" style="color: var(--ink-500); border: none;" @click="clearSelection">
                <X class="h-3 w-3" /> Désélec.
              </button>
            </div>
          </div>
        </Transition>

        <!-- Footer principal -->
        <footer class="flex items-center justify-between gap-4 border-t px-5 py-3" style="border-color: var(--surface-3); background: var(--surface);">
          <div class="flex-1">
            <div class="h-1 overflow-hidden" style="background: var(--surface-2);">
              <div class="h-full transition-all duration-300" :style="{
                width: totalActionable ? `${(decidedCount / totalActionable) * 100}%` : '0%',
                background: 'linear-gradient(90deg, var(--gold-600), var(--gold-500))',
              }"></div>
            </div>
            <p class="mt-1.5 font-mono text-[10px]" style="color: var(--ink-400);">
              <kbd>J</kbd>/<kbd>K</kbd> nav · <kbd>1-5</kbd> assign · <kbd>F</kbd> search · <kbd>D</kbd> détections · <kbd>?</kbd> aide
            </p>
          </div>
          <div class="flex items-center gap-2">
            <button class="btn" @click="closePage">Annuler</button>
            <button
              class="btn btn--primary"
              :disabled="!allDecided || submitting"
              @click="submit"
            >
              <Loader2 v-if="submitting" class="h-3 w-3 animate-spin" />
              <Check v-else class="h-3 w-3" />
              Valider listing →
            </button>
          </div>
        </footer>
      </section>
    </div>

    <!-- ═══ Toast décision ═══ -->
    <Transition name="toast">
      <div
        v-if="lastDecisionToast"
        class="fixed bottom-6 left-1/2 z-30 -translate-x-1/2 inline-flex items-center gap-3 rounded-full border px-4 py-2 text-[12px] shadow-lg"
        style="border-color: var(--success); background: var(--ink); color: var(--surface);"
      >
        <CheckCircle2 class="h-4 w-4" :style="{ color: 'var(--success)' }" />
        <span>
          Listing validé ·
          <strong>{{ lastDecisionToast.done }}</strong> assignés ·
          <strong>{{ lastDecisionToast.rejected }}</strong> rejetés ·
          <strong>{{ lastDecisionToast.skipped }}</strong> reportés
        </span>
      </div>
    </Transition>

    <!-- ═══ Search modal ═══ -->
    <CoinSearchModal
      :open="searchTarget !== null"
      @close="searchTarget = null"
      @select="onSearchSelect"
    />

    <!-- ═══ Help overlay ═══ -->
    <div
      v-if="showHelp"
      class="fixed inset-0 z-50 flex items-center justify-center px-6"
      style="background: rgba(14,14,31,.65); backdrop-filter: blur(4px);"
      @click="showHelp = false"
    >
      <article
        class="max-w-md rounded-lg border p-6"
        style="border-color: var(--surface-3); background: var(--surface);"
        @click.stop
      >
        <h2 class="font-display text-lg italic font-semibold" style="color: var(--indigo-700);">
          Raccourcis · Lot review
        </h2>
        <dl class="mt-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">J / K · ↓ ↑</dt>
          <dd style="color: var(--ink-500);">Crop actif suivant / précédent</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">1 – 5</dt>
          <dd style="color: var(--ink-500);">Assigner le candidat top-N au crop actif</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">F</dt>
          <dd style="color: var(--ink-500);">Sélecteur libre (CoinSearchModal)</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">R</dt>
          <dd style="color: var(--ink-500);">Rejeter le crop actif (raison <em>other</em>)</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">N</dt>
          <dd style="color: var(--ink-500);">Skip le crop actif</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">O / V / U</dt>
          <dd style="color: var(--ink-500);">Face : avers / revers / inconnu (sur assign)</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">D</dt>
          <dd style="color: var(--ink-500);">Toggle overlay détections (Stage 2)</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">⏎</dt>
          <dd style="color: var(--ink-500);">Valider le listing (si toutes décidées)</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">Esc</dt>
          <dd style="color: var(--ink-500);">Fermer overlay / désélec. / page</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">?</dt>
          <dd style="color: var(--ink-500);">Toggle cette aide</dd>
        </dl>
        <p class="mt-5 text-[11px]" style="color: var(--ink-400);">
          Cliquer ailleurs ou
          <kbd class="mx-1 inline-block rounded px-1 py-0.5 font-mono text-[10px]" style="background: var(--surface-1); border: 1px solid var(--surface-3);">Esc</kbd>
          pour fermer.
        </p>
      </article>
    </div>

  </div>
</template>

<style scoped>
.kicker {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.18em;
}
.kicker-line {
  width: 18px; height: 1px; background: var(--gold-600);
}

kbd {
  display: inline-block;
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 3px;
  background: var(--surface-1);
  border: 0.5px solid var(--surface-3);
  color: var(--ink-700);
}

.tag {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 1px 8px;
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-size: 10px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  border: 0.5px solid var(--surface-3);
  border-radius: 999px;
  color: var(--ink-500);
  background: var(--surface);
}
.tag--gold { color: var(--gold-600); border-color: var(--gold-600); }
.tag--indigo { color: var(--indigo-700); border-color: var(--indigo-700); }

.nav-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 32px; height: 32px;
  border: 0.5px solid var(--surface-3);
  background: var(--surface);
  color: var(--ink-500);
  cursor: pointer;
  transition: all 140ms ease;
}
.nav-btn:hover:not(:disabled) {
  color: var(--gold-600);
  border-color: var(--gold-600);
  background: color-mix(in srgb, var(--gold-600) 6%, var(--surface));
}
.nav-btn:disabled { opacity: 0.35; cursor: not-allowed; }
.nav-btn--text {
  width: auto;
  padding: 0 10px;
  gap: 6px;
}

.switch {
  width: 28px; height: 16px;
  border-radius: 999px;
  background: var(--surface-2);
  border: 0.5px solid var(--surface-3);
  position: relative;
  transition: all 160ms ease;
}
.switch::after {
  content: ""; position: absolute;
  top: 1.5px; left: 1.5px;
  width: 11px; height: 11px;
  border-radius: 50%;
  background: var(--ink-400);
  transition: all 160ms ease;
}
.switch.on {
  background: color-mix(in srgb, var(--gold-600) 22%, var(--surface));
  border-color: var(--gold-600);
}
.switch.on::after {
  left: 14px;
  background: var(--gold-600);
}

.raw-thumb {
  position: relative;
  flex: 0 0 auto;
  width: 64px; height: 64px;
  border: 0.5px solid var(--surface-3);
  background: var(--surface-1);
  cursor: pointer;
  overflow: hidden;
  padding: 0;
  transition: all 140ms ease;
}
.raw-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.raw-thumb:hover { border-color: var(--ink-500); }
.raw-thumb.active {
  border-color: var(--gold-600);
  box-shadow: 0 0 0 1.5px var(--gold-600);
}
.tag-overlay {
  position: absolute;
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-size: 9px;
  color: white;
  text-shadow: 0 1px 2px rgba(0,0,0,.6);
}
.tag-overlay--tl { top: 2px; left: 4px; }
.tag-overlay--br { bottom: 2px; right: 4px; }

.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  font-weight: 600;
  font-size: 11px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  border: 0.5px solid var(--surface-3);
  background: var(--surface);
  color: var(--ink-700);
  cursor: pointer;
  transition: all 160ms ease;
}
.btn:hover:not(:disabled) { border-color: var(--ink); }
.btn:disabled { opacity: 0.4; cursor: not-allowed; }
.btn--primary {
  background: var(--ink);
  color: var(--surface);
  border-color: var(--ink);
}
.btn--primary:hover:not(:disabled) {
  background: var(--gold-600);
  border-color: var(--gold-600);
}

.bulk-btn {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 4px 10px;
  border: 0.5px solid;
  background: var(--surface);
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-size: 11px;
  cursor: pointer;
  transition: all 140ms ease;
  list-style: none;
}
.bulk-btn::-webkit-details-marker { display: none; }

.bulk-enter-active, .bulk-leave-active { transition: all 180ms ease-out; }
.bulk-enter-from, .bulk-leave-to { opacity: 0; transform: translateY(8px); }

.toast-enter-active, .toast-leave-active { transition: all 200ms ease-out; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translate(-50%, 8px); }
</style>
