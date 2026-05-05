<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import {
  Check, CheckSquare, ChevronDown, Keyboard, Loader2, Package, RotateCcw, Search,
  SkipForward, Square, Trash2, X,
} from 'lucide-vue-next'
import {
  decideLot, fetchLot, LotReviewError,
  type LotAssignment, type LotDetail, type LotRejectReason,
} from '../composables/useLotReview'
import { useLotReviewKeybinds } from '../composables/useLotReviewKeybinds'
import CoinSearchModal from './CoinSearchModal.vue'
import DinoSuggestions from './DinoSuggestions.vue'
import DinoVerdict from './DinoVerdict.vue'
import AutoValidateVerdict from './AutoValidateVerdict.vue'
import TextSignals from './TextSignals.vue'
import type { CoinSearchEntry } from '../composables/useCoinsSearch'
import type { DinoSuggestion } from '../composables/useDinoSuggestions'

const props = defineProps<{ listingKey: string | null }>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'decided', payload: { listingKey: string; done: number; rejected: number; skipped: number }): void
}>()

// ─── State ─────────────────────────────────────────────────────────────

const detail = ref<LotDetail | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

// Local pending decisions, keyed by asset_id.
type PendingDecision =
  | { kind: 'assign'; eurio_id: string; label: string; face: 'obverse' | 'reverse' | 'unknown' }
  | { kind: 'reject'; reason: LotRejectReason }
  | { kind: 'skip' }
const decisions = ref<Record<string, PendingDecision>>({})

// Search modal target : either one asset, or a bulk apply.
type SearchTarget = { kind: 'single'; assetId: string } | { kind: 'bulk' } | null
const searchTarget = ref<SearchTarget>(null)
const submitting = ref(false)

// Bulk selection : asset_ids cochés via checkbox.
const selected = ref<Set<string>>(new Set())
const bulkMode = computed(() => selected.value.size > 0)
const bulkRejectOpen = ref(false)

// Crop actif (curseur clavier). Index dans `actionableCrops`.
const activeCropIndex = ref(0)
const showHelp = ref(false)
const cropRowRefs = ref<Record<string, HTMLElement | null>>({})

const REJECT_REASONS: { value: LotRejectReason; label: string }[] = [
  { value: 'not_a_coin', label: 'Pas une pièce' },
  { value: 'out_of_scope', label: 'Hors-scope' },
  { value: 'duplicate_in_listing', label: 'Doublon dans le listing' },
  { value: 'unreadable', label: 'Illisible' },
  { value: 'other', label: 'Autre' },
]

// ─── Derived ───────────────────────────────────────────────────────────

const allCrops = computed(() =>
  detail.value?.images.flatMap((im) => im.crops.map((c) => ({ image: im, crop: c }))) ?? [],
)

// Crops actionnables = ceux qui ont une review_id (sont en queue lot).
// Premier asset_id du lot — sert à fetcher le panel TextSignals (le
// signal vit au niveau du listing, donc pareil pour tous les crops d'un
// même source_image. Le drawer lot agrège un seul listing.)
const firstAssetId = computed<string | null>(() => {
  if (!detail.value) return null
  for (const im of detail.value.images) {
    if (im.crops.length > 0) return im.crops[0].asset_id
  }
  return null
})

const actionableCrops = computed(() =>
  allCrops.value.filter(({ crop }) => crop.review_id),
)

const decidedCount = computed(() => Object.keys(decisions.value).length)
const totalActionable = computed(() => actionableCrops.value.length)
const allDecided = computed(
  () => totalActionable.value > 0 && decidedCount.value === totalActionable.value,
)

// ─── Loaders ───────────────────────────────────────────────────────────

async function load(key: string) {
  loading.value = true
  error.value = null
  detail.value = null
  decisions.value = {}
  selected.value = new Set()
  bulkRejectOpen.value = false
  activeCropIndex.value = 0
  showHelp.value = false
  try {
    detail.value = await fetchLot(key)
  } catch (err) {
    error.value = err instanceof LotReviewError ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

watch(
  () => props.listingKey,
  (k) => {
    if (k) void load(k)
  },
  { immediate: true },
)

// ─── Actions ───────────────────────────────────────────────────────────

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
  const assignTo = (assetId: string) => {
    next[assetId] = {
      kind: 'assign',
      eurio_id: entry.eurio_id,
      label: entry.label,
      face: 'obverse',
    }
  }
  if (target.kind === 'single') {
    assignTo(target.assetId)
  } else {
    for (const id of selected.value) assignTo(id)
    selected.value = new Set()
  }
  decisions.value = next
  searchTarget.value = null
}

function rejectCrop(assetId: string, reason: LotRejectReason) {
  decisions.value = {
    ...decisions.value,
    [assetId]: { kind: 'reject', reason },
  }
}

function skipCrop(assetId: string) {
  decisions.value = {
    ...decisions.value,
    [assetId]: { kind: 'skip' },
  }
}

function clearDecision(assetId: string) {
  const next = { ...decisions.value }
  delete next[assetId]
  decisions.value = next
}

function assignToCandidate(assetId: string, eurio_id: string, label: string) {
  decisions.value = {
    ...decisions.value,
    [assetId]: { kind: 'assign', eurio_id, label, face: 'obverse' },
  }
}

function assignFromDino(assetId: string, s: DinoSuggestion) {
  const label = [s.country_name, s.year, s.theme].filter(Boolean).join(' · ')
  assignToCandidate(assetId, s.eurio_id, label)
}

async function submit() {
  if (!detail.value || !allDecided.value || submitting.value) return
  submitting.value = true
  try {
    const assignments: LotAssignment[] = Object.entries(decisions.value).map(
      ([asset_id, d]) => {
        if (d.kind === 'assign') {
          return { asset_id, eurio_id: d.eurio_id, face: d.face }
        }
        if (d.kind === 'reject') return { asset_id, reject_reason: d.reason }
        return { asset_id, skip: true }
      },
    )
    const res = await decideLot(detail.value.listing_key, assignments)
    emit('decided', {
      listingKey: detail.value.listing_key,
      done: res.done,
      rejected: res.rejected,
      skipped: res.skipped,
    })
  } catch (err) {
    error.value = err instanceof LotReviewError ? err.message : String(err)
  } finally {
    submitting.value = false
  }
}

function cropDecisionLabel(assetId: string): string | null {
  const d = decisions.value[assetId]
  if (!d) return null
  if (d.kind === 'assign') {
    const faceCode = d.face === 'obverse' ? 'O' : d.face === 'reverse' ? 'V' : 'U'
    return `→ ${d.label} · ${faceCode}`
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

// ─── Active crop (keyboard cursor) ─────────────────────────────────────

const activeCrop = computed(() => actionableCrops.value[activeCropIndex.value] ?? null)
const activeAssetId = computed(() => activeCrop.value?.crop.asset_id ?? null)

function setActiveIndex(idx: number) {
  if (!actionableCrops.value.length) return
  const max = actionableCrops.value.length - 1
  const clamped = Math.max(0, Math.min(max, idx))
  activeCropIndex.value = clamped
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

// ─── Keyboard actions on active crop ───────────────────────────────────

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
  if (!cur || cur.kind !== 'assign') return  // face only meaningful on assign
  decisions.value = {
    ...decisions.value,
    [id]: { ...cur, face },
  }
}

function kbSubmit() {
  if (allDecided.value && !submitting.value) void submit()
}

function toggleHelp() { showHelp.value = !showHelp.value }

function closeOverlay() {
  if (showHelp.value) { showHelp.value = false; return }
  if (searchTarget.value) { searchTarget.value = null; return }
  if (bulkRejectOpen.value) { bulkRejectOpen.value = false; return }
  if (bulkMode.value) { clearSelection(); return }
  emit('close')
}

const keyboardEnabled = computed(
  () => !!props.listingKey && !showHelp.value && searchTarget.value === null,
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

// ─── Bulk selection ────────────────────────────────────────────────────

function toggleSelected(assetId: string) {
  const next = new Set(selected.value)
  if (next.has(assetId)) next.delete(assetId)
  else next.add(assetId)
  selected.value = next
}

function clearSelection() {
  selected.value = new Set()
  bulkRejectOpen.value = false
}

function bulkReject(reason: LotRejectReason) {
  const next = { ...decisions.value }
  for (const id of selected.value) {
    next[id] = { kind: 'reject', reason }
  }
  decisions.value = next
  bulkRejectOpen.value = false
  selected.value = new Set()
}

function bulkSkip() {
  const next = { ...decisions.value }
  for (const id of selected.value) {
    next[id] = { kind: 'skip' }
  }
  decisions.value = next
  selected.value = new Set()
}

// Master checkbox : tri-state — true if all actionables selected, false if none,
// indeterminate if partial (handled by ARIA + visual on the icon).
const allActionableSelected = computed(() => {
  if (!totalActionable.value) return false
  return actionableCrops.value.every(({ crop }) => selected.value.has(crop.asset_id))
})

function toggleAllSelection() {
  if (allActionableSelected.value) {
    clearSelection()
  } else {
    selected.value = new Set(actionableCrops.value.map(({ crop }) => crop.asset_id))
  }
}
</script>

<template>
  <Transition name="drawer">
    <div
      v-if="listingKey"
      class="fixed inset-0 z-40 flex"
      role="dialog"
      aria-modal="true"
    >
      <!-- Backdrop -->
      <div
        class="flex-1 cursor-pointer"
        style="background: rgba(14,14,31,.55); backdrop-filter: blur(4px);"
        @click="emit('close')"
      />
      <!-- Panel -->
      <aside
        class="flex w-full max-w-[85vw] flex-col border-l shadow-2xl lg:max-w-[78vw]"
        style="border-color: var(--surface-3); background: var(--surface);"
      >
        <!-- Header -->
        <header
          class="flex items-start justify-between gap-4 border-b px-6 py-4"
          style="border-color: var(--surface-3); background: var(--surface);"
        >
          <div class="min-w-0 flex-1">
            <p
              class="inline-flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider"
              style="color: var(--gold-600);"
            >
              <Package class="h-3 w-3" />
              {{ detail?.is_lot_suspected ? 'Lot listing' : 'Multi-crop single' }}
              <span class="opacity-50">·</span>
              <span style="color: var(--ink-500);">{{ listingKey }}</span>
            </p>
            <h2
              v-if="detail"
              class="mt-1 truncate font-display text-base italic font-semibold"
              :title="detail.listing_title ?? ''"
              style="color: var(--ink);"
            >
              « {{ detail.listing_title ?? '— sans titre —' }} »
            </h2>
            <div
              v-if="detail"
              class="mt-1 flex flex-wrap items-baseline gap-x-4 gap-y-1 font-mono text-[11px]"
              style="color: var(--ink-500);"
            >
              <span><span class="opacity-70">src&nbsp;·</span>
                <span class="ml-1" style="color: var(--ink-700);">{{ detail.source }}</span></span>
              <span v-if="detail.listing_price !== null">
                <span class="opacity-70">prix&nbsp;·</span>
                <span class="ml-1" style="color: var(--ink-700);">{{ detail.listing_price.toFixed(2) }}€</span>
              </span>
              <span v-if="detail.target_eurio_id">
                <span class="opacity-70">cible&nbsp;·</span>
                <span class="ml-1" style="color: var(--indigo-700);">{{ detail.target_eurio_id }}</span>
              </span>
            </div>
            <AutoValidateVerdict
              v-if="firstAssetId"
              :asset-id="firstAssetId"
              class="mt-2"
            />
            <TextSignals
              v-if="firstAssetId"
              :asset-id="firstAssetId"
              variant="compact"
              class="mt-2"
            />
            <DinoVerdict
              v-if="firstAssetId"
              :asset-id="firstAssetId"
              variant="compact"
              class="mt-1"
            />
          </div>
          <div class="flex items-center gap-1.5">
            <button
              type="button"
              class="inline-flex items-center gap-1 rounded-md border px-2 py-1.5 text-[11px] transition-colors"
              style="border-color: var(--surface-3); color: var(--ink-500); background: var(--surface-1);"
              title="Raccourcis clavier (?)"
              @click="toggleHelp"
            >
              <Keyboard class="h-3.5 w-3.5" />
              <span class="font-mono opacity-70">?</span>
            </button>
            <button
              type="button"
              class="rounded-md border p-1.5 transition-colors"
              style="border-color: var(--surface-3); color: var(--ink-500); background: var(--surface-1);"
              title="Fermer (Esc)"
              @click="emit('close')"
            >
              <X class="h-4 w-4" />
            </button>
          </div>
        </header>

        <!-- Body : 2 colonnes -->
        <div class="flex flex-1 overflow-hidden">
          <!-- Loading / error -->
          <div
            v-if="loading"
            class="flex flex-1 items-center justify-center gap-2 text-sm"
            style="color: var(--ink-400);"
          >
            <Loader2 class="h-4 w-4 animate-spin" /> Chargement…
          </div>
          <div
            v-else-if="error"
            class="m-6 flex-1 rounded-lg border px-4 py-3 text-sm"
            style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 4%, var(--surface)); color: var(--danger);"
          >
            {{ error }}
          </div>

          <template v-else-if="detail">
            <!-- Panel gauche : galerie images -->
            <section
              class="flex w-2/5 flex-col gap-3 overflow-y-auto border-r px-5 py-4"
              style="border-color: var(--surface-3); background: var(--surface-1);"
            >
              <p
                class="font-mono text-[10px] uppercase tracking-wider"
                style="color: var(--ink-500);"
              >
                Images du listing · {{ detail.images.length }}
              </p>
              <article
                v-for="im in detail.images"
                :key="im.source_image_id"
                class="overflow-hidden rounded-md border"
                style="border-color: var(--surface-3); background: var(--surface);"
              >
                <div class="aspect-[4/3] overflow-hidden" style="background: var(--surface-2);">
                  <img
                    :src="im.raw_url"
                    :alt="`image ${im.image_index ?? '?'}`"
                    class="h-full w-full object-contain"
                    loading="lazy"
                  />
                </div>
                <div
                  class="flex items-center justify-between px-2 py-1.5 font-mono text-[10px]"
                  style="background: var(--surface-1); color: var(--ink-500);"
                >
                  <span>img {{ im.image_index ?? '?' }}</span>
                  <span>{{ im.crops.length }} crop{{ im.crops.length > 1 ? 's' : '' }}</span>
                </div>
              </article>
            </section>

            <!-- Panel droit : crops avec actions -->
            <section class="flex flex-1 flex-col overflow-hidden">
              <div class="flex-1 overflow-y-auto px-5 py-4">
                <div
                  class="mb-3 flex items-center justify-between gap-3 font-mono text-[10px] uppercase tracking-wider"
                  style="color: var(--ink-500);"
                >
                  <p>
                    Crops à reviewer ·
                    <span style="color: var(--gold-600);">
                      {{ decidedCount }} / {{ totalActionable }}
                    </span>
                  </p>
                  <button
                    v-if="totalActionable > 0"
                    type="button"
                    class="inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 transition-colors"
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
                </div>

                <p
                  v-if="!actionableCrops.length"
                  class="rounded-md border-2 border-dashed px-4 py-8 text-center text-sm"
                  style="border-color: var(--surface-3); color: var(--ink-400);"
                >
                  Aucun crop en review pour ce listing.
                </p>

                <ul class="flex flex-col gap-3">
                  <li
                    v-for="({ crop, image }, idx) in actionableCrops"
                    :key="crop.asset_id"
                    :ref="(el) => setRowRef(crop.asset_id, el)"
                    class="flex gap-3 rounded-md border px-3 py-2 transition-shadow"
                    :style="{
                      borderColor: selected.has(crop.asset_id)
                        ? 'var(--indigo-700)'
                        : decisions[crop.asset_id] ? cropDecisionTone(crop.asset_id) : 'var(--surface-3)',
                      background: selected.has(crop.asset_id)
                        ? 'color-mix(in srgb, var(--indigo-700) 5%, var(--surface))'
                        : decisions[crop.asset_id]
                          ? `color-mix(in srgb, ${cropDecisionTone(crop.asset_id)} 5%, var(--surface))`
                          : 'var(--surface)',
                      boxShadow: idx === activeCropIndex
                        ? '0 0 0 2px var(--gold-600)'
                        : 'none',
                    }"
                    @click="setActiveIndex(idx)"
                  >
                    <!-- Bulk select checkbox -->
                    <button
                      type="button"
                      class="flex h-5 w-5 shrink-0 items-center justify-center self-start rounded border transition-colors"
                      :style="{
                        borderColor: selected.has(crop.asset_id) ? 'var(--indigo-700)' : 'var(--surface-3)',
                        background: selected.has(crop.asset_id) ? 'var(--indigo-700)' : 'var(--surface-1)',
                        color: 'var(--surface)',
                      }"
                      :aria-pressed="selected.has(crop.asset_id)"
                      :title="selected.has(crop.asset_id) ? 'Désélectionner' : 'Sélectionner'"
                      @click="toggleSelected(crop.asset_id)"
                    >
                      <Check v-if="selected.has(crop.asset_id)" class="h-3 w-3" />
                    </button>

                    <!-- Crop thumbnail -->
                    <div
                      class="h-20 w-20 shrink-0 overflow-hidden rounded-md border"
                      style="border-color: var(--surface-3); background: var(--surface-1);"
                    >
                      <img
                        :src="crop.crop_url"
                        :alt="`crop ${crop.crop_index}`"
                        class="h-full w-full object-cover"
                        loading="lazy"
                      />
                    </div>

                    <!-- Crop body -->
                    <div class="flex min-w-0 flex-1 flex-col">
                      <div class="flex items-baseline justify-between">
                        <p class="font-mono text-[11px]" style="color: var(--ink-500);">
                          img {{ image.image_index ?? '?' }} · crop {{ crop.crop_index }}
                        </p>
                        <p
                          v-if="cropDecisionLabel(crop.asset_id)"
                          class="font-mono text-[11px]"
                          :style="{ color: cropDecisionTone(crop.asset_id) }"
                        >
                          {{ cropDecisionLabel(crop.asset_id) }}
                        </p>
                      </div>

                      <!-- Top candidates -->
                      <div
                        v-if="crop.candidate_eurio_ids.length"
                        class="mt-1 flex flex-wrap gap-1"
                      >
                        <button
                          v-for="cand in crop.candidate_eurio_ids.slice(0, 3)"
                          :key="cand.eurio_id"
                          type="button"
                          class="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-[10px] transition-colors"
                          :style="{
                            borderColor: isAssignedTo(crop.asset_id, cand.eurio_id)
                              ? 'var(--success)'
                              : 'var(--surface-3)',
                            color: 'var(--ink-700)',
                            background: 'var(--surface-1)',
                          }"
                          :title="cand.label"
                          @click="assignToCandidate(crop.asset_id, cand.eurio_id, cand.label)"
                        >
                          {{ cand.eurio_id }}
                          <span style="color: var(--ink-400);">{{ (cand.score * 100).toFixed(0) }}%</span>
                        </button>
                      </div>

                      <!-- Dino suggestions (V1, aide visuelle compacte) -->
                      <div class="mt-2">
                        <DinoSuggestions
                          :asset-id="crop.asset_id"
                          variant="compact"
                          @select="(s) => assignFromDino(crop.asset_id, s)"
                        />
                      </div>

                      <!-- Action buttons -->
                      <div class="mt-2 flex flex-wrap items-center gap-1.5">
                        <button
                          type="button"
                          class="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 font-mono text-[10px] transition-colors"
                          style="border-color: var(--surface-3); color: var(--indigo-700); background: var(--surface);"
                          @click="openSearchFor(crop.asset_id)"
                        >
                          <Search class="h-2.5 w-2.5" /> Assigner…
                        </button>
                        <details class="relative">
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
                          @click="skipCrop(crop.asset_id)"
                        >
                          <SkipForward class="h-2.5 w-2.5" /> Skip
                        </button>
                        <button
                          v-if="decisions[crop.asset_id]"
                          type="button"
                          class="inline-flex items-center gap-1 rounded-md px-2 py-0.5 font-mono text-[10px] transition-colors"
                          style="color: var(--ink-400);"
                          title="Annuler la décision"
                          @click="clearDecision(crop.asset_id)"
                        >
                          <RotateCcw class="h-2.5 w-2.5" />
                        </button>
                      </div>
                    </div>
                  </li>
                </ul>
              </div>

              <!-- Sub-footer bulk (au-dessus du footer principal, visible si ≥1 sélection) -->
              <Transition name="bulk">
                <footer
                  v-if="bulkMode"
                  class="flex flex-wrap items-center justify-between gap-3 border-t px-5 py-2.5"
                  style="
                    border-color: var(--indigo-700);
                    background: color-mix(in srgb, var(--indigo-700) 6%, var(--surface));
                  "
                >
                  <p class="font-mono text-[11px]" style="color: var(--indigo-700);">
                    <span class="font-semibold">{{ selected.size }}</span>
                    <span class="ml-1 uppercase tracking-wider opacity-80">crop{{ selected.size > 1 ? 's' : '' }} sélectionné{{ selected.size > 1 ? 's' : '' }}</span>
                  </p>
                  <div class="flex flex-wrap items-center gap-1.5">
                    <button
                      type="button"
                      class="inline-flex items-center gap-1 rounded-md border px-2.5 py-1 font-mono text-[11px] transition-colors"
                      style="border-color: var(--indigo-700); color: var(--indigo-700); background: var(--surface);"
                      @click="openBulkSearch"
                    >
                      <Search class="h-3 w-3" /> Assigner…
                    </button>
                    <details
                      class="relative"
                      :open="bulkRejectOpen"
                      @toggle="(e) => (bulkRejectOpen = (e.currentTarget as HTMLDetailsElement).open)"
                    >
                      <summary
                        class="inline-flex cursor-pointer list-none items-center gap-1 rounded-md border px-2.5 py-1 font-mono text-[11px]"
                        style="border-color: var(--danger); color: var(--danger); background: var(--surface);"
                      >
                        <Trash2 class="h-3 w-3" /> Rejeter
                        <ChevronDown class="h-3 w-3 opacity-60" />
                      </summary>
                      <div
                        class="absolute right-0 bottom-full z-10 mb-1 flex flex-col rounded-md border shadow-lg"
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
                          @click="bulkReject(r.value)"
                        >
                          {{ r.label }}
                        </button>
                      </div>
                    </details>
                    <button
                      type="button"
                      class="inline-flex items-center gap-1 rounded-md border px-2.5 py-1 font-mono text-[11px] transition-colors"
                      style="border-color: var(--surface-3); color: var(--ink-700); background: var(--surface);"
                      @click="bulkSkip"
                    >
                      <SkipForward class="h-3 w-3" /> Skip
                    </button>
                    <button
                      type="button"
                      class="inline-flex items-center gap-1 rounded-md px-2 py-1 font-mono text-[11px] transition-colors"
                      style="color: var(--ink-500);"
                      title="Vider la sélection"
                      @click="clearSelection"
                    >
                      <X class="h-3 w-3" /> Désélec.
                    </button>
                  </div>
                </footer>
              </Transition>

              <!-- Footer -->
              <footer
                class="flex items-center justify-between gap-4 border-t px-5 py-3"
                style="border-color: var(--surface-3); background: var(--surface);"
              >
                <p class="font-mono text-[11px]" style="color: var(--ink-500);">
                  <span :style="{ color: allDecided ? 'var(--success)' : 'var(--ink-700)' }">
                    {{ decidedCount }}
                  </span>
                  / {{ totalActionable }} décisions
                </p>
                <div class="flex items-center gap-2">
                  <button
                    type="button"
                    class="inline-flex items-center gap-1 rounded-md border px-3 py-1 text-[11px]"
                    style="border-color: var(--surface-3); color: var(--ink-500); background: var(--surface-1);"
                    @click="emit('close')"
                  >
                    Annuler
                  </button>
                  <button
                    type="button"
                    class="inline-flex items-center gap-1.5 rounded-md px-3 py-1 font-mono text-[11px] uppercase tracking-wider text-white transition-opacity disabled:cursor-not-allowed disabled:opacity-40"
                    style="background: var(--gold-600);"
                    :disabled="!allDecided || submitting"
                    @click="submit"
                  >
                    <Loader2 v-if="submitting" class="h-3 w-3 animate-spin" />
                    <Check v-else class="h-3 w-3" />
                    Valider listing
                  </button>
                </div>
              </footer>
            </section>
          </template>
        </div>
      </aside>

      <!-- Coin search modal pour Assigner (single ou bulk) -->
      <CoinSearchModal
        :open="searchTarget !== null"
        @close="searchTarget = null"
        @select="onSearchSelect"
      />

      <!-- Help overlay raccourcis clavier -->
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
            <dt class="font-mono text-[12px]" style="color: var(--ink-700);">⏎</dt>
            <dd style="color: var(--ink-500);">Valider le listing (si toutes décidées)</dd>
            <dt class="font-mono text-[12px]" style="color: var(--ink-700);">Esc</dt>
            <dd style="color: var(--ink-500);">Fermer overlay / désélec. / drawer</dd>
            <dt class="font-mono text-[12px]" style="color: var(--ink-700);">?</dt>
            <dd style="color: var(--ink-500);">Toggle cette aide</dd>
          </dl>
          <p class="mt-5 text-[11px]" style="color: var(--ink-400);">
            Cliquer ailleurs ou
            <kbd
              class="mx-1 inline-block rounded px-1 py-0.5 font-mono text-[10px]"
              style="background: var(--surface-1); border: 1px solid var(--surface-3);"
            >Esc</kbd>
            pour fermer.
          </p>
        </article>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.drawer-enter-active,
.drawer-leave-active {
  transition: opacity 200ms ease-out;
}
.drawer-enter-active aside,
.drawer-leave-active aside {
  transition: transform 240ms ease-out;
}
.drawer-enter-from,
.drawer-leave-to {
  opacity: 0;
}
.drawer-enter-from aside,
.drawer-leave-to aside {
  transform: translateX(100%);
}

.bulk-enter-active,
.bulk-leave-active {
  transition: transform 180ms ease-out, opacity 180ms ease-out;
}
.bulk-enter-from,
.bulk-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
</style>
