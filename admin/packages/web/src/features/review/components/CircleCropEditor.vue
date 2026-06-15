<script setup lang="ts">
// Éditeur de cercle pour re-cropper à la main une vraie pièce mal cadrée
// (chantier crop-quality-overhaul, Session B). On dessine le cercle sur le
// RAW (jamais sur le crop 224) ; l'aperçu canvas 224 est INDICATIF (rendu
// client approximatif), le crop SAUVÉ est toujours le _crop_mask_resize_float
// canonique côté Python (POST manual-crop). → zéro divergence de format.
//
// Interactions : drag dans le cercle = déplacer le centre ; drag la poignée du
// rim, molette OU slider = rayon. Coords manipulées en px NATIFS du raw.
//
// Alignement SVG↔image : le SVG est positionné EXACTEMENT sur la box rendue de
// l'<img> (offset + ResizeObserver) — pas de wrapper aspect-ratio qui décale.
// Les couleurs passent par `style` (les var(--token) ne marchent PAS dans les
// attributs SVG `stroke`/`fill`).

import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { Check, Loader2, X } from 'lucide-vue-next'
import {
  fetchAssetCropEditContext,
  fetchCropEditContext,
  manualCrop,
  manualCropAsset,
  type CropEditContext,
} from '../composables/useReviewApi'
import { addLotCrop, type LotCrop } from '../composables/useLotReview'

// Trois points d'entrée pour le MÊME éditeur (cœur backend partagé) :
//   - `reviewId`   : depuis la review queue (le crop appartient à une review).
//   - `assetId`    : recadrage EN PLACE d'une vignette coin-detail (hors queue).
//   - `addContext` : ADD-CROP (Chunk D) — pas d'asset existant, on crée un
//                    nouveau crop sur une source_image depuis un cercle dessiné
//                    (rattrapage des pièces ratées par la détection).
// Exactement l'un des trois doit être fourni.
const props = defineProps<{
  reviewId?: string
  assetId?: string
  addContext?: {
    listingKey: string
    sourceImageId: string
    source: string
    rawUrl: string
    rawWidth: number
    rawHeight: number
    initialCircle?: { cx: number; cy: number; r: number } | null
  }
}>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'saved'): void
  (e: 'created', crop: LotCrop): void
}>()

const isAddMode = computed(() => props.addContext != null)

// Marge radiale du format prod (CropConfig.margin_frac = 0.02).
const MARGIN_FRAC = 0.02

const ctx = ref<CropEditContext | null>(null)
const loadError = ref<string | null>(null)
const saving = ref(false)

// Cercle courant en px NATIFS du raw.
const cx = ref(0)
const cy = ref(0)
const r = ref(0)

const natW = computed(() => ctx.value?.raw_width ?? 0)
const natH = computed(() => ctx.value?.raw_height ?? 0)

// URL distincte (`?canvas=1`) pour le raw dessiné sur canvas : l'img est
// chargée en crossorigin='anonymous' (sinon canvas tainté → pas d'aperçu).
// La marquer différemment de l'URL d'AFFICHAGE (plate lot, sans crossorigin)
// évite que le navigateur réutilise une entrée de cache non-CORS pour la
// requête CORS — ce qui cassait l'aperçu (lot) ou l'affichage (selon l'ordre).
// Endpoint backend `/sources/.../file` : ignore les query params inconnus.
const canvasRawSrc = computed(() => {
  const u = ctx.value?.raw_url
  if (!u) return ''
  return `${u}${u.includes('?') ? '&' : '?'}canvas=1`
})
const rMax = computed(() => Math.max(natW.value, natH.value) || 1)

// Refs DOM.
const stageEl = ref<HTMLElement | null>(null)
const svgEl = ref<SVGSVGElement | null>(null)
const rawImg = ref<HTMLImageElement | null>(null)
const previewCanvas = ref<HTMLCanvasElement | null>(null)
const imgLoaded = ref(false)

// Box rendue de l'<img> (relative au stage positionné) → le SVG se cale dessus.
const imgBox = ref({ left: 0, top: 0, width: 0, height: 0 })
const overlayStyle = computed(() => ({
  left: `${imgBox.value.left}px`,
  top: `${imgBox.value.top}px`,
  width: `${imgBox.value.width}px`,
  height: `${imgBox.value.height}px`,
}))

function syncOverlay() {
  const img = rawImg.value
  if (!img) return
  imgBox.value = {
    left: img.offsetLeft,
    top: img.offsetTop,
    width: img.offsetWidth,
    height: img.offsetHeight,
  }
}

let ro: ResizeObserver | null = null

// Poignée de rayon, à droite du centre. Taille constante à l'écran (~10px).
const handleX = computed(() => cx.value + r.value)
const handleY = computed(() => cy.value)
const uiScale = computed(() => {
  const w = imgBox.value.width
  return w && natW.value ? natW.value / w : 1
})
const handleR = computed(() => 10 * uiScale.value)

async function load() {
  loadError.value = null
  try {
    // Add-crop : pas de fetch, on construit le contexte depuis le raw du lot
    // (déjà connu côté front) — l'asset n'existe pas encore.
    if (props.addContext) {
      const ac = props.addContext
      const c: CropEditContext = {
        asset_id: '',
        source: ac.source,
        raw_url: ac.rawUrl,
        crop_url: '',
        raw_width: ac.rawWidth,
        raw_height: ac.rawHeight,
        hint: ac.initialCircle ?? null,
      }
      ctx.value = c
      if (c.hint) {
        cx.value = c.hint.cx; cy.value = c.hint.cy; r.value = c.hint.r
      } else {
        cx.value = (c.raw_width ?? 0) / 2
        cy.value = (c.raw_height ?? 0) / 2
        r.value = Math.min(c.raw_width ?? 0, c.raw_height ?? 0) * 0.3
      }
      return
    }
    const c = props.assetId
      ? await fetchAssetCropEditContext(props.assetId)
      : await fetchCropEditContext(props.reviewId!)
    ctx.value = c
    // Démarre sur le cercle dominant détecté (source mono-pièce, crop souvent
    // sous-dimensionné) quand présent, sinon sur le crop actuel (hint bbox).
    const start = c.suggested_circle ?? c.hint
    if (start) {
      cx.value = start.cx
      cy.value = start.cy
      r.value = start.r
    } else {
      cx.value = (c.raw_width ?? 0) / 2
      cy.value = (c.raw_height ?? 0) / 2
      r.value = Math.min(c.raw_width ?? 0, c.raw_height ?? 0) * 0.3
    }
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : String(err)
  }
}

onMounted(() => {
  void load()
  window.addEventListener('resize', syncOverlay)
  window.addEventListener('keydown', onKey, true)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', syncOverlay)
  window.removeEventListener('keydown', onKey, true)
  ro?.disconnect()
})
watch(() => [props.reviewId, props.assetId], load)

// ─── Mapping pointeur → coords natives ───────────────────────────────────

function toNative(evt: PointerEvent): { x: number; y: number } {
  const rect = svgEl.value!.getBoundingClientRect()
  return {
    x: ((evt.clientX - rect.left) / rect.width) * natW.value,
    y: ((evt.clientY - rect.top) / rect.height) * natH.value,
  }
}

type DragMode = 'move' | 'radius' | null
const dragMode = ref<DragMode>(null)
let moveOffsetX = 0
let moveOffsetY = 0

function clampCircle() {
  cx.value = Math.max(0, Math.min(natW.value, cx.value))
  cy.value = Math.max(0, Math.min(natH.value, cy.value))
  r.value = Math.max(8, Math.min(rMax.value, r.value))
}

function startMove(evt: PointerEvent) {
  const p = toNative(evt)
  moveOffsetX = p.x - cx.value
  moveOffsetY = p.y - cy.value
  dragMode.value = 'move'
  svgEl.value?.setPointerCapture(evt.pointerId)
}

function startRadius(evt: PointerEvent) {
  dragMode.value = 'radius'
  svgEl.value?.setPointerCapture(evt.pointerId)
  evt.stopPropagation()
}

function onPointerMove(evt: PointerEvent) {
  if (!dragMode.value) return
  const p = toNative(evt)
  if (dragMode.value === 'move') {
    cx.value = p.x - moveOffsetX
    cy.value = p.y - moveOffsetY
  } else {
    r.value = Math.hypot(p.x - cx.value, p.y - cy.value)
  }
  clampCircle()
}

function endDrag(evt: PointerEvent) {
  dragMode.value = null
  svgEl.value?.releasePointerCapture?.(evt.pointerId)
}

function onWheel(evt: WheelEvent) {
  evt.preventDefault()
  const step = Math.max(2, r.value * 0.04)
  r.value += evt.deltaY < 0 ? step : -step
  clampCircle()
}

function onSlider(evt: Event) {
  r.value = Number((evt.target as HTMLInputElement).value)
  clampCircle()
}

function bumpRadius(delta: number) {
  r.value += delta
  clampCircle()
}

// ─── Aperçu canvas 224 (indicatif, miroir de _crop_mask_resize_float) ────

function drawPreview() {
  const canvas = previewCanvas.value
  const img = rawImg.value
  if (!canvas || !img || !imgLoaded.value || !natW.value) return
  const S = 224
  const g = canvas.getContext('2d')
  if (!g) return
  g.fillStyle = '#000'
  g.fillRect(0, 0, S, S)

  const margin = r.value * MARGIN_FRAC
  const half = r.value + margin
  const x0 = Math.max(0, cx.value - half)
  const y0 = Math.max(0, cy.value - half)
  const x1 = Math.min(natW.value, cx.value + half)
  const y1 = Math.min(natH.value, cy.value + half)
  const side = Math.min(x1 - x0, y1 - y0)
  if (side <= 0) return

  const scale = S / side
  const ccx = (cx.value - x0) * scale
  const ccy = (cy.value - y0) * scale
  const cr = r.value * scale

  g.save()
  g.beginPath()
  g.arc(ccx, ccy, cr, 0, Math.PI * 2)
  g.clip()
  // Canvas potentiellement "tainted" (raw cross-origin via ML_API) : on ne
  // lit jamais les pixels (pas de toDataURL), donc l'affichage reste permis.
  g.drawImage(img, x0, y0, side, side, 0, 0, S, S)
  g.restore()
}

function onImgLoad() {
  imgLoaded.value = true
  syncOverlay()
  if (rawImg.value && !ro) {
    ro = new ResizeObserver(syncOverlay)
    ro.observe(rawImg.value)
  }
  drawPreview()
}

watch([cx, cy, r, imgLoaded], drawPreview)

// ─── Sauvegarde ──────────────────────────────────────────────────────────

async function save() {
  if (saving.value) return
  saving.value = true
  try {
    const circle = { cx: cx.value, cy: cy.value, r: r.value }
    if (props.addContext) {
      const crop = await addLotCrop(
        props.addContext.listingKey, props.addContext.sourceImageId, circle)
      emit('created', crop)
      emit('close')
      return
    }
    if (props.assetId) await manualCropAsset(props.assetId, circle)
    else await manualCrop(props.reviewId!, circle)
    emit('saved')
    emit('close')
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : String(err)
  } finally {
    saving.value = false
  }
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    e.stopPropagation()
    emit('close')
    return
  }
  if (e.key === 'Enter') {
    // Entrée = « Valider le recadrage » (PAS la pièce — le clavier global
    // est désactivé tant que l'éditeur est ouvert). No-op si pas prêt.
    if (!ctx.value || saving.value) return
    e.stopPropagation()
    e.preventDefault()
    void save()
    return
  }
  // Ajustement fin au clavier (px natifs) : +/− = rayon, flèches = déplacement.
  // Shift = pas grossier (×4). Pas de base = 3 % du rayon (≥ 2 px) → réactif quel
  // que soit le zoom. clampCircle borne aux limites de l'image.
  if (!ctx.value) return
  const step = Math.max(2, r.value * 0.03) * (e.shiftKey ? 4 : 1)
  let handled = true
  switch (e.key) {
    case '+': case '=': r.value += step; break
    case '-': case '_': r.value -= step; break
    case 'ArrowUp': cy.value -= step; break
    case 'ArrowDown': cy.value += step; break
    case 'ArrowLeft': cx.value -= step; break
    case 'ArrowRight': cx.value += step; break
    default: handled = false
  }
  if (handled) {
    e.preventDefault()
    e.stopPropagation()
    clampCircle()
  }
}
</script>

<template>
  <div
    class="fixed inset-0 z-40 flex flex-col"
    style="background: rgba(14,14,31,.78); backdrop-filter: blur(6px);"
  >
    <!-- Header -->
    <header
      class="flex items-center justify-between gap-4 border-b px-8 py-3"
      style="border-color: var(--surface-3); background: var(--surface);"
    >
      <div>
        <h2 class="font-display text-base italic font-semibold" style="color: var(--indigo-700);">
          {{ isAddMode ? 'Ajouter un crop' : 'Recadrer le crop' }}
        </h2>
        <p class="mt-0.5 text-xs" style="color: var(--ink-500);">
          Dessine le cercle sur la pièce — glisser le centre, poignée / molette / slider pour le rayon.
          Clavier : <span class="font-mono">+ −</span> rayon, <span class="font-mono">↑ ↓ ← →</span> déplacer
          (<span class="font-mono">Maj</span> = pas large), <span class="font-mono">⏎</span> valider.
        </p>
      </div>
      <button
        type="button"
        class="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px] font-mono uppercase tracking-wider"
        style="border-color: var(--surface-3); color: var(--ink-500); background: var(--surface-1);"
        @click="emit('close')"
      >
        <X class="h-3 w-3" /> Esc
      </button>
    </header>

    <!-- Erreur de chargement -->
    <div v-if="loadError" class="flex flex-1 items-center justify-center px-8">
      <p class="max-w-md text-center text-sm" style="color: var(--danger);">{{ loadError }}</p>
    </div>

    <!-- Éditeur -->
    <div v-else-if="ctx" class="flex flex-1 items-stretch gap-6 overflow-hidden p-6">
      <!-- Raw + cercle (le SVG se cale sur la box rendue de l'img) -->
      <div ref="stageEl" class="relative flex min-h-0 min-w-0 flex-1 items-center justify-center">
        <img
          ref="rawImg"
          :src="canvasRawSrc"
          alt="raw"
          crossorigin="anonymous"
          class="block max-h-full max-w-full select-none rounded-lg"
          draggable="false"
          @load="onImgLoad"
        />
        <svg
          ref="svgEl"
          class="absolute"
          :style="overlayStyle"
          :viewBox="`0 0 ${natW} ${natH}`"
          preserveAspectRatio="none"
          style="cursor: grab; touch-action: none;"
          @pointerdown="startMove"
          @pointermove="onPointerMove"
          @pointerup="endDrag"
          @pointercancel="endDrag"
          @wheel="onWheel"
        >
          <defs>
            <mask id="circle-hole">
              <rect x="0" y="0" :width="natW" :height="natH" fill="white" />
              <circle :cx="cx" :cy="cy" :r="r" fill="black" />
            </mask>
          </defs>
          <!-- Voile sombre hors du cercle conservé -->
          <rect
            x="0" y="0" :width="natW" :height="natH"
            fill="rgba(8,8,20,0.55)" mask="url(#circle-hole)"
          />
          <!-- Contour du cercle (couleur via style : var() interdit en attribut SVG) -->
          <circle
            :cx="cx" :cy="cy" :r="r"
            fill="transparent"
            :stroke-width="2.5 * uiScale"
            :style="{ stroke: 'var(--gold-soft)' }"
          />
          <!-- Centre -->
          <circle :cx="cx" :cy="cy" :r="handleR * 0.35" :style="{ fill: 'var(--gold-soft)' }" />
          <!-- Poignée de rayon -->
          <circle
            :cx="handleX" :cy="handleY" :r="handleR"
            stroke="white" :stroke-width="2 * uiScale"
            :style="{ fill: 'var(--indigo-700)', cursor: 'ew-resize' }"
            @pointerdown="startRadius"
          />
        </svg>
      </div>

      <!-- Aperçu + contrôles -->
      <aside class="flex w-[260px] shrink-0 flex-col gap-4">
        <div>
          <p class="font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-400);">
            Aperçu 224 · indicatif
          </p>
          <div
            class="mt-2 overflow-hidden rounded-lg border"
            style="border-color: var(--surface-3); background: var(--surface-1);"
          >
            <canvas
              ref="previewCanvas"
              width="224"
              height="224"
              class="block h-auto w-full"
            />
          </div>
        </div>

        <!-- Contrôle explicite du rayon -->
        <div class="flex flex-col gap-1.5">
          <div class="flex items-center justify-between">
            <span class="font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-400);">
              Rayon
            </span>
            <span class="font-mono text-[10px]" style="color: var(--ink-500);">
              r {{ Math.round(r) }} px
            </span>
          </div>
          <div class="flex items-center gap-2">
            <button
              type="button"
              class="h-6 w-6 shrink-0 rounded-md border font-mono text-[13px] leading-none"
              style="border-color: var(--surface-3); color: var(--ink-700); background: var(--surface-1);"
              title="Réduire le rayon"
              @click="bumpRadius(-4)"
            >−</button>
            <input
              type="range"
              class="crop-range min-w-0 flex-1"
              :min="8"
              :max="rMax"
              :step="1"
              :value="r"
              @input="onSlider"
            />
            <button
              type="button"
              class="h-6 w-6 shrink-0 rounded-md border font-mono text-[13px] leading-none"
              style="border-color: var(--surface-3); color: var(--ink-700); background: var(--surface-1);"
              title="Agrandir le rayon"
              @click="bumpRadius(4)"
            >+</button>
          </div>
          <p class="font-mono text-[10px]" style="color: var(--ink-400);">
            cx {{ Math.round(cx) }} · cy {{ Math.round(cy) }}
          </p>
        </div>

        <div class="mt-auto flex flex-col gap-2">
          <button
            type="button"
            class="inline-flex items-center justify-center gap-2 rounded-md px-4 py-2 text-[13px] font-semibold transition-all"
            :disabled="saving"
            style="background: var(--indigo-700); color: var(--surface);"
            @click="save"
          >
            <Loader2 v-if="saving" class="h-3.5 w-3.5 animate-spin" />
            <Check v-else class="h-3.5 w-3.5" />
            {{ saving ? 'Enregistrement…' : (isAddMode ? 'Ajouter le crop' : 'Valider le recadrage') }}
            <span
              v-if="!saving"
              class="ml-1 rounded px-1 font-mono text-[10px] uppercase tracking-wider"
              style="background: rgba(255,255,255,.18);"
            >⏎</span>
          </button>
          <button
            type="button"
            class="inline-flex items-center justify-center gap-1.5 rounded-md border px-4 py-2 text-[12px]"
            style="border-color: var(--surface-3); color: var(--ink-500); background: var(--surface-1);"
            @click="emit('close')"
          >
            Annuler
          </button>
        </div>
      </aside>
    </div>

    <!-- Chargement -->
    <div v-else class="flex flex-1 items-center justify-center">
      <Loader2 class="h-6 w-6 animate-spin" style="color: var(--ink-400);" />
    </div>
  </div>
</template>

<style scoped>
.crop-range {
  appearance: none;
  height: 4px;
  border-radius: 9999px;
  background: var(--surface-3);
  cursor: pointer;
}
.crop-range::-webkit-slider-thumb {
  appearance: none;
  width: 16px;
  height: 16px;
  border-radius: 9999px;
  background: var(--indigo-700);
  border: 2px solid var(--surface);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.25);
}
.crop-range::-moz-range-thumb {
  width: 16px;
  height: 16px;
  border: 2px solid var(--surface);
  border-radius: 9999px;
  background: var(--indigo-700);
}
</style>
