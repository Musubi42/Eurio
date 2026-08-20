<script setup lang="ts">
// Vue de travail d'un lot — Specimen Plate (Phase 2 Chunk 5).
//
// C'est une VUE, pas une page : elle reçoit le listing à ouvrir et son
// PÉRIMÈTRE en props, et demande la navigation par un événement. Deux hôtes
// s'en servent — la route `/review/lot/:listing_key` (LotReviewDetailPage) et
// le bandeau de la page cohorte, qui la monte pour dérouler les lots d'une
// classe un par un sans quitter sa file. Même patron que ReviewPage →
// SingleReviewView.
//
// ⚠️ Le `scope` n'est pas décoratif : il voyage jusqu'à `GET /review-queue/
// lots/{key}` et détermine `prev/next_listing_key`. Sans lui, « lot suivant »
// déroule la file lot GLOBALE (5413 items) et sort de la classe au premier clic.
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

import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  ArrowLeft, ArrowRight, Check, CheckCircle2, ChevronDown, Crop,
  Keyboard, Loader2, Plus, RotateCcw, ScanSearch, SkipForward,
  Trash2, X,
} from 'lucide-vue-next'
import {
  decideLot, detectLotImage, fetchLot, LotReviewError, requalifyLotAsSingle,
  syncLotCrops,
  type LotAssignment, type LotCandidate, type LotCrop, type LotDetail,
  type LotRejectReason,
} from '../composables/useLotReview'
import { useLotReviewKeybinds } from '../composables/useLotReviewKeybinds'
import ReviewRightColumn from '../components/ReviewRightColumn.vue'
import SplitCompare from '../components/SplitCompare.vue'
import CircleCropEditor from '../components/CircleCropEditor.vue'
import type { CoinSearchEntry } from '../composables/useCoinsSearch'
import type { DinoSuggestion } from '../composables/useDinoSuggestions'

const props = defineProps<{
  /** Le listing à ouvrir. */
  listingKey: string
  /**
   * Le périmètre de la file qu'on déroule, transmis tel quel à l'API
   * (`dino_class`/`dino_rank`/`dino_min_spread`, ou `design_group`/`cohort_id`/
   * `target_eurio_id`). Il ne change pas le contenu du lot, seulement ses
   * voisins — mais c'est lui qui fait que « suivant » reste dans la classe.
   */
  scope?: Record<string, string>
}>()

const emit = defineEmits<{
  /** Aller à ce listing — l'hôte décide comment (param de route ou query). */
  (e: 'navigate', listingKey: string): void
  /** Plus de lot dans le périmètre : l'hôte reprend la main. */
  (e: 'exhausted'): void
}>()

// ─── State ─────────────────────────────────────────────────────────────

const detail = ref<LotDetail | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const showHelp = ref(false)
// Démarre en COMPARAISON (crop ↔ canonique) : l'identification est l'acte
// dominant ; le plateau (curation des cercles) est sur D à la demande. Cf.
// refonte UX review lot (comparaison-primaire).
const showOverlay = ref(false)        // toggle Stage 2 cercles (D)
const autoAdvance = ref(true)          // validate→next chain
const submitting = ref(false)
const lastDecisionToast = ref<{ done: number; rejected: number; skipped: number } | null>(null)

// Decisions per asset_id, accumulé localement, envoyé au "Valider listing".
type PendingDecision =
  | { kind: 'assign'; eurio_id: string; label: string; face: 'obverse' | 'reverse' | 'unknown' }
  | { kind: 'reject'; reason: LotRejectReason }
  | { kind: 'skip' }
const decisions = ref<Record<string, PendingDecision>>({})

// Active raw (image index) — défaut première image.
const activeRawIndex = ref(0)

// Active crop (cursor clavier) — index dans `actionableCrops`.
const activeCropIndex = ref(0)
const cropRowRefs = ref<Record<string, HTMLElement | null>>({})

// Hover bidirectionnel : asset_id survolé (crop card ↔ anneau overlay).
const hoveredAssetId = ref<string | null>(null)

// Re-crop manuel (touche E) — éditeur de cercle sur le crop actif, réutilise
// CircleCropEditor (entrée reviewId). Cf. Chunk B plan review-lot.
const showCropEditor = ref(false)
// Cache-bust post-recrop par asset_id : le fichier crop est réécrit au même
// chemin → ?b=<ts> force le refetch sans refetch tout le lot (qui effacerait
// les décisions en cours). Aligné single (cropBust).
const cropBustByAsset = ref<Record<string, number>>({})
// Bumpé après recrop → ReviewRightColumn refetch les suggestions Dino
// (recalculées server-side sur le nouveau crop). Aligné single.
const dinoReloadKey = ref(0)

// Re-détection à la demande (Chunk C) — relance detect_circles_multi sur
// l'image active quand le scrape a raté des pièces. Coûteux → manuel.
const detecting = ref(false)
const detectError = ref<string | null>(null)

// Add-crop (Chunk D) — éditeur de cercle sur l'image active pour créer un
// nouveau crop là où la détection a raté. `addCropCircle` pré-remplit le
// cercle (depuis une détection cliquée) ou null (tracé manuel).
const showAddCrop = ref(false)
const addCropCircle = ref<{ cx: number; cy: number; r: number } | null>(null)

// ─── Colonne droite — state aligné single ──────────────────────────────
// `mode` = 'auto' (Top N + Dino) ou 'free' (FreeSelectorPanel inline).
// `focusedCandidateIdx` = quel candidat Top N est focused (null = aucun
// ou la cible eBay l'est). `freeSearchCandidate` = sélection libre
// pending (badge affiché en mode auto si ≠ cible).
//
// Reset à chaque changement de crop actif pour repartir sur un état
// propre (la cible est de nouveau focused par défaut visuellement).
const mode = ref<'auto' | 'free'>('auto')
const focusedCandidateIdx = ref<number | null>(null)
// Candidat explicitement SÉLECTIONNÉ (recherche libre OU suggestion Dino) :
// pilote la canonique de SplitCompare. Porte sa vignette pour que la grosse
// canonique suive la sélection (sinon elle restait sur la cible eBay).
const freeSearchCandidate = ref<{ eurio_id: string; label: string; canonical_thumb_url?: string } | null>(null)

const REJECT_REASONS: { value: LotRejectReason; label: string }[] = [
  { value: 'not_a_coin', label: 'Pas une pièce' },
  { value: 'out_of_scope', label: 'Hors-scope' },
  { value: 'duplicate_in_listing', label: 'Doublon dans le listing' },
  { value: 'unreadable', label: 'Illisible' },
  { value: 'other', label: 'Autre' },
]

// ─── Derived ───────────────────────────────────────────────────────────

const listingKey = computed<string>(() => props.listingKey)

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

// ── PÊCHE — quels crops de ce lot sont de la classe qu'on pêche ────────────
// Un coffret peut porter 36 vignettes dont UNE seule appartient à la classe.
// Le back le sait (`matches_dino_class`) : l'écran le montre, et s'ouvre
// dessus. Sans ça, on rouvre à chaque lot la même corvée de balayage.
const pecheOn = computed(() => Boolean(props.scope?.dino_class))
// Triés par MARGE décroissante, et c'est le point : un coffret mélange 1 cent
// et 2 €, et la banque — qui ne contient que des 2 € — rattache la piécette à
// la classe la plus proche avec une marge dérisoire. Ouvrir sur le premier
// crop par index, c'était ouvrir sur elle. Le crop le plus NET d'abord.
const matchingCrops = computed(
  () => actionableCrops.value
    .filter(({ crop }) => crop.matches_dino_class === true)
    .sort((a, b) => (b.crop.dino_spread ?? -1) - (a.crop.dino_spread ?? -1)),
)
const nMatching = computed(() => matchingCrops.value.length)
/** La marge du meilleur candidat — dit d'un coup d'œil ce que vaut ce lot. */
const bestSpread = computed(() => matchingCrops.value[0]?.crop.dino_spread ?? null)
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

// Crops de la photo active uniquement, avec review_id (actionnables).
// Utilisé pour la bande du bas : la vue est locale à l'image affichée.
const activeImageCrops = computed(() =>
  activeImage.value?.crops.filter((c) => c.review_id) ?? [],
)

// Mappe asset_id → index dans `actionableCrops` (global) pour que les
// actions clavier (setActiveIndex) restent cohérentes.
const globalIndexByAssetId = computed(() => {
  const m: Record<string, number> = {}
  actionableCrops.value.forEach(({ crop }, idx) => { m[crop.asset_id] = idx })
  return m
})

// SVG viewBox = dimensions natives du raw (les détections sont dans cet espace).
const overlayViewBox = computed(() => {
  const im = activeImage.value
  if (!im || !im.raw_width || !im.raw_height) return '0 0 1000 750'
  return `0 0 ${im.raw_width} ${im.raw_height}`
})

// eurio_id assigné au crop actif (pour le feedback de sélection dans ReviewRightColumn).
const activeCropAssignedEurioId = computed<string | null>(() => {
  const id = activeAssetId.value
  if (!id) return null
  const d = decisions.value[id]
  return d?.kind === 'assign' ? d.eurio_id : null
})

// Candidat actuellement "focused" pour le crop actif. Sert à alimenter
// SplitCompare (la canonique à droite). Ordre de priorité :
//   1. freeSearchCandidate (sélection libre pending)
//   2. Top N à focusedCandidateIdx
//   3. cible eBay du listing (par défaut, comme single)
//   4. null (aucun visuel canonique)
const focusedCandidate = computed<LotCandidate | { eurio_id: string; label: string; canonical_thumb_url?: string } | null>(() => {
  if (freeSearchCandidate.value) return freeSearchCandidate.value
  const a = activeCrop.value
  if (a && focusedCandidateIdx.value !== null) {
    const c = a.crop.candidate_eurio_ids[focusedCandidateIdx.value]
    if (c) return c
  }
  if (detail.value?.target_candidate) return detail.value.target_candidate
  return null
})

const focusedCanonicalUrl = computed<string | null>(() => {
  const f = focusedCandidate.value
  if (!f) return null
  return ('canonical_thumb_url' in f && f.canonical_thumb_url) || null
})

// ─── Loaders ───────────────────────────────────────────────────────────

async function load(key: string) {
  loading.value = true
  error.value = null
  detail.value = null
  decisions.value = {}
  activeCropIndex.value = 0
  activeRawIndex.value = 0
  showHelp.value = false
  mode.value = 'auto'
  focusedCandidateIdx.value = null
  freeSearchCandidate.value = null
  try {
    detail.value = await fetchLot(key, props.scope)
  } catch (err) {
    error.value = err instanceof LotReviewError ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

// À l'ouverture d'un lot pêché, le curseur se pose sur le premier crop de la
// classe plutôt que sur le crop 1. Le tri, c'est l'acte ; balayer trente-cinq
// vignettes avant lui, c'est la corvée qu'on est venu supprimer.
watch(matchingCrops, (list) => {
  if (!pecheOn.value || !list.length) return
  const first = list[0].crop.asset_id
  const idx = globalIndexByAssetId.value[first]
  if (idx != null && idx !== activeCropIndex.value) setActiveIndex(idx)
})

// `immediate: true` couvre déjà le montage initial — pas de onMounted en
// double (sinon 2 appels identiques au endpoint lourd). Couvre aussi la
// navigation prev/next (la route change → listingKey change → reload).
watch(listingKey, (k) => { if (k) void load(k) }, { immediate: true })

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

// ─── Handlers de la colonne droite (ReviewRightColumn) ─────────────────
// Click = FOCUS uniquement (visuel), pas d'assign. Aligné sur single :
// l'utilisateur presse Enter pour valider le focused candidate. Dino et
// FreeSelectorPanel sont des actions explicites → assign immédiat.

function enterFreeMode() {
  mode.value = 'free'
}

function exitFreeMode() {
  mode.value = 'auto'
}

function onTargetFocus() {
  // La cible eBay est le focus implicite quand focusedCandidateIdx est
  // null et qu'aucune sélection libre n'est en attente. Cliquer la cible
  // remet juste cet état "défaut" — pas d'assign.
  focusedCandidateIdx.value = null
  freeSearchCandidate.value = null
}

function onCandidateFocus(idx: number) {
  focusedCandidateIdx.value = idx
  freeSearchCandidate.value = null
}

function onDinoSelect(s: DinoSuggestion) {
  const a = activeCrop.value
  if (!a) return
  const label = `${s.eurio_id} (Dino · ${(s.sim * 100).toFixed(0)}%)`
  assignToCandidate(a.crop.asset_id, s.eurio_id, label)
  // La canonique de SplitCompare suit la sélection (vignette = avers Dino).
  freeSearchCandidate.value = {
    eurio_id: s.eurio_id, label, canonical_thumb_url: s.obverse_url ?? undefined,
  }
  focusedCandidateIdx.value = null
}

function onFreeSelect(entry: CoinSearchEntry) {
  const a = activeCrop.value
  if (!a) return
  assignToCandidate(a.crop.asset_id, entry.eurio_id, entry.label)
  freeSearchCandidate.value = {
    eurio_id: entry.eurio_id, label: entry.label,
    canonical_thumb_url: entry.canonical_thumb_url ?? undefined,
  }
  exitFreeMode()
}

// ─── Active crop nav ───────────────────────────────────────────────────

function setActiveIndex(idx: number) {
  if (!actionableCrops.value.length) return
  const max = actionableCrops.value.length - 1
  const clamped = Math.max(0, Math.min(max, idx))
  activeCropIndex.value = clamped
  // Reset focus state pour repartir avec la cible eBay comme défaut
  // visuel sur le nouveau crop (évite focusedCandidateIdx qui pointe sur
  // un index inexistant si le crop précédent avait plus de candidats).
  focusedCandidateIdx.value = null
  freeSearchCandidate.value = null
  if (mode.value === 'free') mode.value = 'auto'
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

// Clic sur une vignette photo (haut) : change la photo ET active son premier
// crop actionnable, pour que la bande filtrée ait toujours un crop actif
// surligné (cohérence vert). Photo sans crop → simple bascule.
function selectImage(idx: number) {
  const im = detail.value?.images[idx]
  const first = im?.crops.find((c) => c.review_id)
  if (first) {
    const gi = globalIndexByAssetId.value[first.asset_id]
    if (gi !== undefined) { setActiveIndex(gi); return }
  }
  activeRawIndex.value = idx
}

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
      emit('navigate', detail.value.next_listing_key)
    } else {
      emit('exhausted')
    }
  } catch (err) {
    error.value = err instanceof LotReviewError ? err.message : String(err)
  } finally {
    submitting.value = false
  }
}

// « Pas un lot » (S) — faux positif de la classif v2 : le listing repart en
// single. Écriture immédiate (pas une décision d'attribution) puis on chaîne
// vers le listing suivant (comme submit), ou retour à la grille.
const requalifyingSingle = ref(false)
async function requalifyAsSingle() {
  if (!detail.value || requalifyingSingle.value) return
  requalifyingSingle.value = true
  const next = detail.value.next_listing_key
  try {
    await requalifyLotAsSingle(detail.value.listing_key)
    if (autoAdvance.value && next) {
      emit('navigate', next)
    } else {
      emit('exhausted')
    }
  } catch (err) {
    error.value = err instanceof LotReviewError ? err.message : String(err)
  } finally {
    requalifyingSingle.value = false
  }
}

function gotoPrev() {
  if (detail.value?.prev_listing_key) emit('navigate', detail.value.prev_listing_key)
}
function gotoNext() {
  if (detail.value?.next_listing_key) emit('navigate', detail.value.next_listing_key)
}
function closePage() {
  emit('exhausted')
}

// ─── Keyboard ──────────────────────────────────────────────────────────

function kbCandidateFocus(idx: number) {
  // 1-5 : focus le Top N idx du crop actif (pas d'assign — l'utilisateur
  // valide ensuite avec Enter, comme single).
  const a = activeCrop.value
  if (!a) return
  if (idx < 0 || idx >= a.crop.candidate_eurio_ids.length) return
  focusedCandidateIdx.value = idx
  freeSearchCandidate.value = null
}
function kbRejectActive() {
  const id = activeAssetId.value
  if (!id) return
  rejectCrop(id, 'other')
  nextCrop()
}
function kbSkipActive() {
  const id = activeAssetId.value
  if (!id) return
  skipCrop(id)
  nextCrop()
}
function kbOpenSearchActive() {
  if (!activeAssetId.value) return
  enterFreeMode()
}
function kbSetFaceActive(face: 'obverse' | 'reverse' | 'unknown') {
  const id = activeAssetId.value
  if (!id) return
  const cur = decisions.value[id]
  if (!cur || cur.kind !== 'assign') return
  decisions.value = { ...decisions.value, [id]: { ...cur, face } }
}

// Enter : si le listing est complètement décidé, submit. Sinon, assigne
// le focused candidate (cible eBay par défaut) au crop actif et advance.
// Si le crop actif a déjà une décision, on advance sans toucher.
function kbValidate() {
  if (!detail.value) return
  if (allDecided.value && !submitting.value) {
    void submit()
    return
  }
  const a = activeCrop.value
  if (!a) return
  // Crop déjà décidé → on advance simplement
  if (decisions.value[a.crop.asset_id]) {
    nextCrop()
    return
  }
  // Sinon assigne le focused
  const f = focusedCandidate.value
  if (!f) return
  assignToCandidate(a.crop.asset_id, f.eurio_id, f.label)
  nextCrop()
}

function nextRaw() {
  if (!detail.value || detail.value.images.length < 2) return
  const max = detail.value.images.length - 1
  activeRawIndex.value = Math.min(max, activeRawIndex.value + 1)
}
function prevRaw() {
  if (!detail.value || detail.value.images.length < 2) return
  activeRawIndex.value = Math.max(0, activeRawIndex.value - 1)
}

function toggleHelp() { showHelp.value = !showHelp.value }
function toggleOverlay() { showOverlay.value = !showOverlay.value }

function closeOverlay() {
  if (showHelp.value) { showHelp.value = false; return }
  if (mode.value === 'free') { exitFreeMode(); return }
  closePage()
}

// En mode free l'input texte du FreeSelectorPanel peut capter `/` — on
// désactive les autres raccourcis pour éviter le double-effet.
const keyboardEnabled = computed(
  () => !showHelp.value && mode.value !== 'free'
    && !showCropEditor.value && !showAddCrop.value,
)

// E : ouvre l'éditeur de re-crop sur le crop actif. Réutilise CircleCropEditor
// (entrée reviewId) — opère sur le RAW complet, ne régénère que CE crop
// (apply_manual_crop keyé asset_id, crops frères intacts).
function openRecropActive() {
  if (activeCrop.value?.crop.review_id) showCropEditor.value = true
}

// Re-détecte l'image active à la demande (Chunk C). Met à jour
// activeImage.detections en place (overlay live) sans refetch du lot. Les
// cercles sans crop deviennent candidats add-crop (Chunk D).
async function reDetectActiveImage() {
  const im = activeImage.value
  if (!im || detecting.value || !detail.value) return
  detecting.value = true
  detectError.value = null
  try {
    const res = await detectLotImage(detail.value.listing_key, im.source_image_id)
    im.detections = res.detections
    if (!showOverlay.value) showOverlay.value = true  // montre la plate
  } catch (err) {
    detectError.value = err instanceof LotReviewError ? err.message : String(err)
  } finally {
    detecting.value = false
  }
}

// Resync les crops de l'image active sur les cercles acceptés du constat
// (action explicite, distincte de Re-détecter). Remplace les fichiers de crop
// (re-point/create/delete côté backend) et recompute le Dino → corrige les
// vignettes ET les suggestions. Refuse (409) si un crop est déjà décidé.
async function syncCropsActiveImage() {
  const im = activeImage.value
  if (!im || detecting.value || !detail.value) return
  if (!im.crops.some((c) => c.review_id)) return  // rien à resync
  detecting.value = true
  detectError.value = null
  try {
    const res = await syncLotCrops(detail.value.listing_key, im.source_image_id)
    im.crops = res.crops
    // Les fichiers crop sont réécrits aux mêmes/nouveaux chemins → bust le cache
    // de tous les crops de l'image + relance les suggestions Dino.
    const bust = { ...cropBustByAsset.value }
    for (const c of res.crops) bust[c.asset_id] = Date.now()
    cropBustByAsset.value = bust
    dinoReloadKey.value += 1
    activeCropIndex.value = 0
  } catch (err) {
    detectError.value = err instanceof LotReviewError ? err.message : String(err)
  } finally {
    detecting.value = false
  }
}

// Contexte add-crop pour l'image active (CircleCropEditor mode addContext).
const addCropContext = computed(() => {
  const im = activeImage.value
  if (!im || !detail.value || im.raw_width == null || im.raw_height == null) return null
  return {
    listingKey: detail.value.listing_key,
    sourceImageId: im.source_image_id,
    source: detail.value.source,
    rawUrl: im.raw_url,
    rawWidth: im.raw_width,
    rawHeight: im.raw_height,
    initialCircle: addCropCircle.value,
  }
})

// Ouvre l'éditeur en mode add-crop (cercle vierge = tracé manuel, ou
// pré-rempli depuis une détection sans crop).
function openAddCrop(circle?: { cx: number; cy: number; r: number }) {
  addCropCircle.value = circle ?? null
  showAddCrop.value = true
}

// Crop ajouté : insère le nouveau LotCrop dans l'image active (réactif), le
// rend actionnable, et place le curseur dessus.
function onCropCreated(crop: LotCrop) {
  const im = activeImage.value
  if (im) {
    im.crops.push(crop)
    void nextTick(() => {
      const idx = actionableCrops.value.findIndex((c) => c.crop.asset_id === crop.asset_id)
      if (idx >= 0) activeCropIndex.value = idx
    })
  }
  showAddCrop.value = false
  addCropCircle.value = null
}

// Re-crop validé : bust le cache du crop recadré (sans refetch tout le lot,
// qui effacerait les décisions) + relance les suggestions Dino.
function onCropSaved() {
  const id = activeAssetId.value
  if (id) cropBustByAsset.value = { ...cropBustByAsset.value, [id]: Date.now() }
  dinoReloadKey.value += 1
  showCropEditor.value = false
}

useLotReviewKeybinds(keyboardEnabled, {
  onCandidateFocus: kbCandidateFocus,
  onValidate: kbValidate,
  onRejectActive: kbRejectActive,
  onSkipActive: kbSkipActive,
  onOpenSearch: kbOpenSearchActive,
  onSetFaceActive: kbSetFaceActive,
  onNextCrop: nextCrop,
  onPrevCrop: prevCrop,
  onNextRaw: nextRaw,
  onPrevRaw: prevRaw,
  onToggleHelp: toggleHelp,
  onCloseOverlay: closeOverlay,
  onRequalifySingle: requalifyAsSingle,
  onRecropActive: openRecropActive,
})

// D toggle reste géré ici (pas dans le composable car spécifique à
// l'examination plate du lot).
function onKeydown(e: KeyboardEvent) {
  if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
  if (e.metaKey || e.ctrlKey || e.altKey) return
  if (showHelp.value || mode.value === 'free' || showCropEditor.value || showAddCrop.value) return
  if (e.key === 'd' || e.key === 'D') { toggleOverlay(); e.preventDefault() }
}
onMounted(() => window.addEventListener('keydown', onKeydown))
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
function detectionTagPos(det: { cx: number; cy: number; r: number }) {
  // Place tag in the top-right of the circle (offset by ~r/√2).
  const off = det.r * 0.7
  return { x: det.cx + off, y: det.cy - off }
}

// Couleur de l'anneau SVG selon l'état de décision du crop.
// - actif (en cours de jugement) → vert vif + épaisseur 6px
// - assigné → vert (décision prise)
// - rejeté → rouge
// - survolé → gold (halo hover)
// - non décidé → gris neutre
function detectionRingColor(cropIndex: number | null): string {
  if (cropIndex === null) return 'var(--ink-300)'
  const assetId = assetIdByCropIndex.value[cropIndex]
  if (!assetId) return 'var(--ink-300)'
  if (assetId === activeAssetId.value) return 'var(--success)'
  if (assetId === hoveredAssetId.value) return 'var(--gold-600)'
  const d = decisions.value[assetId]
  if (!d) return 'var(--ink-300)'
  if (d.kind === 'assign') return 'var(--success)'
  if (d.kind === 'reject') return 'var(--danger)'
  return 'var(--ink-400)'
}

function detectionRingWidth(cropIndex: number | null): number {
  if (cropIndex === null) return 2
  const assetId = assetIdByCropIndex.value[cropIndex]
  if (!assetId) return 2
  if (assetId === activeAssetId.value) return 6
  if (assetId === hoveredAssetId.value) return 4
  return 2.5
}

// Cache-bust par phash : le crop est servi à URL stable (/assets/{id}/file).
// Après régénération du fichier (même chemin), le navigateur ressert l'ancienne
// image en cache → ?v=<phash> change quand le contenu change, forçant le refetch.
// `?b=<ts>` ajoute un bust post-recrop in-session (le phash de `detail` n'est
// pas rafraîchi sans refetch — cf. onCropSaved).
function cropSrc(crop: { crop_url: string; phash: number | null; asset_id?: string }): string {
  const base = crop.phash != null ? `${crop.crop_url}?v=${crop.phash}` : crop.crop_url
  const bust = crop.asset_id ? cropBustByAsset.value[crop.asset_id] : undefined
  if (bust == null) return base
  return `${base}${base.includes('?') ? '&' : '?'}b=${bust}`
}

// Couleur de fond du badge numéroté selon l'état.
function detectionBadgeColor(cropIndex: number | null): string {
  if (cropIndex === null) return 'var(--ink-400)'
  const assetId = assetIdByCropIndex.value[cropIndex]
  if (!assetId) return 'var(--ink-400)'
  if (assetId === activeAssetId.value) return 'var(--success)'
  const d = decisions.value[assetId]
  if (!d) return 'var(--ink-400)'
  if (d.kind === 'assign') return 'var(--success)'
  if (d.kind === 'reject') return 'var(--danger)'
  return 'var(--ink-400)'
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
        <button
          class="nav-btn nav-btn--text ml-2"
          :disabled="requalifyingSingle"
          title="Ce listing n'est pas un lot → review single (S)"
          @click="requalifyAsSingle"
        >
          <RotateCcw class="h-3.5 w-3.5" />
          <span class="text-[11px]">Pas un lot</span>
          <kbd>S</kbd>
        </button>
        <button class="nav-btn ml-1" title="Fermer (Esc)" @click="closePage">
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

    <!-- ═══ BODY (2 cols + footer span) ═══ -->
    <div v-else-if="detail" class="flex flex-1 min-h-0 flex-col overflow-hidden">
      <div class="grid flex-1 min-h-0 overflow-hidden" style="grid-template-columns: 1fr 560px;">

      <!-- ─── LEFT : raws strip + central view + crops strip ─── -->
      <section class="flex flex-col gap-3 overflow-hidden border-r px-7 py-5" style="border-color: var(--surface-3);">
        <div class="flex items-baseline justify-between gap-4 shrink-0">
          <div class="flex items-center gap-2.5">
            <span class="kicker-line"></span>
            <span class="kicker" style="color: var(--gold-600);">
              {{ showOverlay ? 'Examination plate' : 'Crop ↔ canonique' }}
            </span>
            <span class="font-mono text-[10px]" style="color: var(--ink-400);">
              <template v-if="showOverlay">img {{ activeRawIndex + 1 }} / {{ detail.images.length }}</template>
              <template v-else-if="activeCrop">crop {{ tagNumberByAssetId[activeCrop.crop.asset_id] ?? '?' }} / {{ totalActionable }}</template>
            </span>
          </div>
          <label class="inline-flex items-center gap-1.5 cursor-pointer text-[11px]" style="color: var(--ink-500);">
            <input v-model="showOverlay" type="checkbox" class="hidden" />
            <span class="switch" :class="{ on: showOverlay }"></span>
            <span>Détections</span>
            <kbd>D</kbd>
          </label>
        </div>

        <!-- Raw selector strip — visible quand >1 raws OU mode plate -->
        <div
          v-if="detail.images.length > 1 || showOverlay"
          class="flex gap-1.5 overflow-x-auto pb-1 shrink-0"
        >
          <button
            v-for="(im, idx) in detail.images"
            :key="im.source_image_id"
            class="raw-thumb"
            :class="{ active: idx === activeRawIndex }"
            :title="`img ${im.image_index ?? idx + 1} · ${im.crops.length} crop${im.crops.length > 1 ? 's' : ''}`"
            @click="selectImage(idx)"
          >
            <img :src="im.raw_url" :alt="`img ${idx + 1}`" loading="lazy" />
            <span class="tag-overlay tag-overlay--tl">{{ idx + 1 }}</span>
            <span class="tag-overlay tag-overlay--br">{{ im.crops.length }} cr.</span>
          </button>
        </div>

        <!-- Central view : examination plate (D ON) OU SplitCompare (D OFF) -->
        <div class="flex-1 min-h-0 overflow-y-auto">
          <!-- Examination plate : raw + SVG overlay (cercles détectés) -->
          <div
            v-if="showOverlay && activeImage"
            class="relative w-full overflow-hidden border"
            :style="{ borderColor: 'var(--surface-3)', background: 'var(--surface-2)', aspectRatio: activeImage.raw_width && activeImage.raw_height ? `${activeImage.raw_width} / ${activeImage.raw_height}` : '4 / 3' }"
          >
            <img
              :src="activeImage.raw_url"
              :alt="`raw ${activeRawIndex + 1}`"
              class="absolute inset-0 h-full w-full object-contain"
            />
            <!-- SVG overlay : anneaux + badges numérotés.
                 Couleurs d'état — actif=vert, assigné=vert, rejeté=rouge,
                 survolé=gold, non décidé=gris. Pointer-events activés sur
                 les cercles acceptés pour le hover bidirectionnel. -->
            <svg
              class="absolute inset-0 h-full w-full"
              style="pointer-events: none;"
              :viewBox="overlayViewBox"
              preserveAspectRatio="xMidYMid meet"
            >
              <!-- Cercles acceptés : anneaux colorés + pointer-events pour hover -->
              <g style="pointer-events: all;">
                <circle
                  v-for="(det, i) in activeImage.detections.filter(d => d.accepted)"
                  :key="`a-${i}`"
                  :cx="det.cx" :cy="det.cy" :r="det.r"
                  fill="none"
                  :stroke="detectionRingColor(det.crop_index)"
                  :stroke-width="detectionRingWidth(det.crop_index)"
                  style="cursor: pointer; transition: stroke 120ms ease, stroke-width 120ms ease;"
                  @mouseenter="hoveredAssetId = det.crop_index !== null ? (assetIdByCropIndex[det.crop_index] ?? null) : null"
                  @mouseleave="hoveredAssetId = null"
                  @click.stop="det.crop_index !== null && assetIdByCropIndex[det.crop_index] ? setActiveIndex(globalIndexByAssetId[assetIdByCropIndex[det.crop_index]] ?? 0) : undefined"
                />
              </g>
              <!-- Badges numérotés (fond coloré selon état) -->
              <g style="pointer-events: none;">
                <g v-for="(det, i) in activeImage.detections.filter(d => d.accepted)" :key="`tag-${i}`">
                  <circle
                    :cx="detectionTagPos(det).x"
                    :cy="detectionTagPos(det).y"
                    r="22"
                    :fill="detectionBadgeColor(det.crop_index)"
                    stroke="var(--surface)" stroke-width="3"
                    style="transition: fill 120ms ease;"
                  />
                  <text
                    :x="detectionTagPos(det).x" :y="detectionTagPos(det).y + 1"
                    text-anchor="middle" dominant-baseline="central"
                    font-family="JetBrains Mono" font-size="20" font-weight="600"
                    fill="var(--surface)"
                  >{{ (det.crop_index ?? 0) + 1 }}</text>
                </g>
              </g>
              <!-- Cercles rejetés par le détecteur : pointillés rouges,
                   CLIQUABLES → add-crop pré-rempli (rattrapage Chunk D). -->
              <g style="pointer-events: all;">
                <circle
                  v-for="(det, i) in activeImage.detections.filter(d => !d.accepted)"
                  :key="`r-${i}`"
                  :cx="det.cx" :cy="det.cy" :r="det.r"
                  fill="transparent" stroke="var(--danger)" stroke-width="2"
                  stroke-dasharray="8 6" opacity="0.7"
                  style="cursor: pointer;"
                  @click.stop="openAddCrop({ cx: det.cx, cy: det.cy, r: det.r })"
                >
                  <title>Ajouter ce crop (écarté : {{ det.reject_reason }})</title>
                </circle>
                <text
                  v-for="(det, i) in activeImage.detections.filter(d => !d.accepted)"
                  :key="`rt-${i}`"
                  :x="det.cx" :y="det.cy + 4" text-anchor="middle"
                  font-family="JetBrains Mono" font-size="14"
                  fill="var(--danger)" opacity="0.8"
                  style="pointer-events: none;"
                >+ {{ det.reject_reason }}</text>
              </g>
            </svg>
          </div>

          <!-- SplitCompare : crop actif ↔ canonique du candidat focused -->
          <SplitCompare
            v-else-if="!showOverlay && activeCrop"
            :crop-url="cropSrc(activeCrop.crop)"
            :canonical-url="focusedCanonicalUrl"
            :bbox="activeCrop.crop.bbox"
          />
        </div>

        <!-- Barre compacte (mode comparaison) : éditer le crop actif à un clic ;
             le plateau complet (re-détecter / sync / crop manuel) est sur D. -->
        <div v-if="!showOverlay && activeImage" class="flex flex-wrap items-center gap-2 shrink-0">
          <button
            type="button"
            class="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 font-mono text-[10px] disabled:opacity-40"
            style="border-color: var(--surface-3); color: var(--ink-700); background: var(--surface);"
            :disabled="!activeCrop?.crop.review_id"
            title="Éditer le crop actif : ajuster le cercle existant sur le raw"
            @click="openRecropActive"
          >
            <Crop class="h-3 w-3" /> Éditer le crop <kbd>E</kbd>
          </button>
          <span class="font-mono text-[10px]" style="color: var(--ink-400);">
            plateau &amp; recadrage des cercles sur <kbd>D</kbd>
          </span>
          <span v-if="detectError" style="color: var(--danger);">{{ detectError }}</span>
        </div>

        <!-- Plate footnote (D ON uniquement) -->
        <div v-if="showOverlay && activeImage" class="flex flex-wrap items-baseline gap-3 font-mono text-[10px] shrink-0" style="color: var(--ink-500);">
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
          <span style="color: var(--surface-3);">·</span>
          <button
            type="button"
            class="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 font-mono text-[10px]"
            style="border-color: var(--surface-3); color: var(--indigo-700); background: var(--surface);"
            :disabled="detecting"
            title="Relancer la détection sur cette image (rattrapage si le scrape a raté des pièces)"
            @click="reDetectActiveImage"
          >
            <Loader2 v-if="detecting" class="h-3 w-3 animate-spin" />
            <ScanSearch v-else class="h-3 w-3" />
            {{ detecting ? 'Détection…' : 'Re-détecter' }}
          </button>
          <button
            type="button"
            class="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 font-mono text-[10px] disabled:opacity-40"
            style="border-color: var(--surface-3); color: var(--indigo-700); background: var(--surface);"
            :disabled="detecting || !activeImageCrops.length"
            title="Resynchroniser les crops sur les cercles acceptés de l'overlay (re-pointe / crée / supprime + recompute Dino). Refusé si un crop est déjà décidé. Relance Re-détecter d'abord si l'overlay est périmé."
            @click="syncCropsActiveImage"
          >
            <RotateCcw class="h-3 w-3" /> Sync crops
          </button>
          <button
            type="button"
            class="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 font-mono text-[10px]"
            style="border-color: var(--surface-3); color: var(--success); background: var(--surface);"
            title="Ajouter un crop à la main sur cette image (pièce ratée par la détection)"
            @click="openAddCrop()"
          >
            <Plus class="h-3 w-3" /> Crop manuel
          </button>
          <button
            type="button"
            class="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 font-mono text-[10px] disabled:opacity-40"
            style="border-color: var(--surface-3); color: var(--ink-700); background: var(--surface);"
            :disabled="!activeCrop?.crop.review_id"
            title="Éditer le crop actif : ajuster le cercle existant sur le raw (≠ ajouter un crop)"
            @click="openRecropActive"
          >
            <Crop class="h-3 w-3" /> Éditer le crop <kbd>E</kbd>
          </button>
          <span v-if="detectError" style="color: var(--danger);">{{ detectError }}</span>
        </div>

        <!-- Crops strip : crops de la photo active uniquement (bande filtrée).
             Compteur GLOBAL (tout listing) affiché dans le label. -->
        <div v-if="activeImageCrops.length" class="shrink-0">
          <p class="mb-1.5 font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
            Crops · photo {{ activeRawIndex + 1 }}
            <span class="opacity-50 ml-2">global :</span>
            <span style="color: var(--gold-600);">{{ decidedCount }}</span>
            / {{ totalActionable }} décidés
            <span v-if="pecheOn" class="ml-2" style="color: var(--indigo-700);">
              · ⌁ {{ nMatching }} de la classe pêchée<span v-if="bestSpread != null">
                · meilleure marge {{ bestSpread.toFixed(3) }}</span>
            </span>
          </p>
          <div class="flex gap-2 overflow-x-auto pb-1">
            <button
              v-for="crop in activeImageCrops"
              :key="crop.asset_id"
              :ref="(el) => setRowRef(crop.asset_id, el)"
              type="button"
              class="crop-strip-card relative flex shrink-0 flex-col items-stretch gap-1 rounded-md border p-1.5 transition-all"
              :style="{
                width: '88px',
                borderColor: crop.asset_id === activeAssetId
                  ? 'var(--success)'
                  : crop.asset_id === hoveredAssetId
                    ? 'var(--gold-600)'
                    : decisions[crop.asset_id]
                      ? cropDecisionTone(crop.asset_id)
                      : 'var(--surface-3)',
                background: crop.asset_id === activeAssetId
                  ? 'color-mix(in srgb, var(--success) 8%, var(--surface))'
                  : crop.asset_id === hoveredAssetId
                    ? 'color-mix(in srgb, var(--gold-600) 6%, var(--surface))'
                    : decisions[crop.asset_id]
                      ? `color-mix(in srgb, ${cropDecisionTone(crop.asset_id)} 5%, var(--surface))`
                      : 'var(--surface)',
                boxShadow: crop.asset_id === activeAssetId
                  ? '0 0 0 2px var(--success)'
                  : crop.asset_id === hoveredAssetId
                    ? '0 0 0 1.5px var(--gold-600)'
                    : 'none',
              }"
              :title="`crop ${crop.crop_index}${decisions[crop.asset_id] ? ' · ' + (cropDecisionLabel(crop.asset_id) ?? '') : ''}`"
              @click="setActiveIndex(globalIndexByAssetId[crop.asset_id] ?? 0)"
              @mouseenter="hoveredAssetId = crop.asset_id"
              @mouseleave="hoveredAssetId = null"
            >
              <!-- Tag badge top-left : couleur selon état décision -->
              <span
                class="absolute -top-1.5 -left-1.5 flex h-5 w-5 items-center justify-center rounded-full font-mono text-[10px] font-semibold"
                :style="{
                  background: crop.asset_id === activeAssetId
                    ? 'var(--success)'
                    : decisions[crop.asset_id]?.kind === 'assign'
                      ? 'var(--success)'
                      : decisions[crop.asset_id]?.kind === 'reject'
                        ? 'var(--danger)'
                        : 'var(--ink-400)',
                  color: 'var(--surface)',
                }"
              >{{ tagNumberByAssetId[crop.asset_id] ?? crop.crop_index + 1 }}</span>

              <!-- PÊCHE : c'est CE crop que la banque rattache à la classe.
                   Une suggestion, pas un verdict — à 0,10 de marge, un
                   standard sur vingt est faux. On le montre, on ne le coche
                   pas. -->
              <span
                v-if="crop.matches_dino_class"
                class="absolute -top-1.5 -right-1.5 flex h-4 w-4 items-center justify-center rounded-full font-mono text-[9px]"
                style="background: var(--indigo-700); color: var(--surface);"
                :title="`Le modèle rattache ce crop à la classe pêchée${crop.dino_spread != null ? ` (marge ${crop.dino_spread.toFixed(3)})` : ''}. À vérifier à l'œil : sur une pièce courante, environ un sur vingt est faux — et une marge sous 0,05 signale souvent une pièce que la banque ne connaît pas du tout, comme une piécette dans un coffret.`"
              >⌁</span>

              <!-- Thumbnail -->
              <div class="aspect-square overflow-hidden rounded border" style="border-color: var(--surface-3); background: var(--surface-1);">
                <img :src="cropSrc(crop)" :alt="`crop ${crop.crop_index}`" class="h-full w-full object-cover" loading="lazy" />
              </div>

              <!-- Decision badge -->
              <p
                v-if="cropDecisionLabel(crop.asset_id)"
                class="truncate font-mono text-[9px]"
                :style="{ color: cropDecisionTone(crop.asset_id) }"
                :title="cropDecisionLabel(crop.asset_id) ?? ''"
              >
                {{ cropDecisionLabel(crop.asset_id) }}
              </p>
              <p v-else class="font-mono text-[9px] opacity-50" style="color: var(--ink-500);">en attente</p>
            </button>
          </div>
        </div>
      </section>

      <!-- ─── RIGHT : ReviewRightColumn (partagée avec single) ─── -->
      <section class="flex flex-col overflow-hidden p-4" style="background: var(--surface-1);">
        <ReviewRightColumn
          :target="detail.target_candidate ?? null"
          :candidates="activeCrop?.crop.candidate_eurio_ids ?? []"
          :mode="mode"
          :focused-candidate-idx="focusedCandidateIdx"
          :free-search-candidate="freeSearchCandidate"
          :asset-id="activeAssetId"
          :assigned-eurio-id="activeCropAssignedEurioId"
          :dino-reload-key="dinoReloadKey"
          class="flex-1 min-h-0"
          @target-focus="onTargetFocus"
          @candidate-focus="onCandidateFocus"
          @dino-select="onDinoSelect"
          @free-select="onFreeSelect"
        />
      </section>
      </div>

      <!-- Footer principal -->
      <footer class="flex items-center justify-between gap-4 border-t px-5 py-3 shrink-0" style="border-color: var(--surface-3); background: var(--surface);">
        <!-- Actions sur le crop actif (clavier-first, mais cliquable aussi) -->
        <div v-if="activeCrop" class="flex items-center gap-1.5">
          <details class="relative" @click.stop>
            <summary
              class="inline-flex cursor-pointer items-center gap-1 rounded-md border px-2 py-1 font-mono text-[10px] list-none"
              style="border-color: var(--surface-3); color: var(--danger); background: var(--surface);"
            >
              <Trash2 class="h-3 w-3" /> Rejeter <kbd>R</kbd> <ChevronDown class="h-3 w-3 opacity-60" />
            </summary>
            <div
              class="absolute left-0 bottom-full z-10 mb-1 flex flex-col rounded-md border shadow-lg"
              style="border-color: var(--surface-3); background: var(--surface); min-width: 180px;"
            >
              <button
                v-for="r in REJECT_REASONS"
                :key="r.value"
                type="button"
                class="px-3 py-1.5 text-left text-[11px]"
                style="color: var(--ink-700);"
                @mouseenter="(e) => ((e.currentTarget as HTMLElement).style.background = 'var(--surface-1)')"
                @mouseleave="(e) => ((e.currentTarget as HTMLElement).style.background = 'transparent')"
                @click="(e) => { kbRejectActive(); rejectCrop(activeAssetId!, r.value); ((e.currentTarget as HTMLElement).closest('details') as HTMLDetailsElement).open = false }"
              >{{ r.label }}</button>
            </div>
          </details>
          <button
            type="button"
            class="inline-flex items-center gap-1 rounded-md border px-2 py-1 font-mono text-[10px]"
            style="border-color: var(--surface-3); color: var(--ink-500); background: var(--surface);"
            @click="kbSkipActive"
          >
            <SkipForward class="h-3 w-3" /> Skip <kbd>N</kbd>
          </button>
          <button
            type="button"
            class="inline-flex items-center gap-1 rounded-md border px-2 py-1 font-mono text-[10px]"
            style="border-color: var(--surface-3); color: var(--ink-500); background: var(--surface);"
            title="Recadrer ce crop (éditeur de cercle sur le raw)"
            @click="openRecropActive"
          >
            <Crop class="h-3 w-3" /> Recadrer <kbd>E</kbd>
          </button>
          <button
            v-if="activeAssetId && decisions[activeAssetId]"
            type="button"
            class="inline-flex items-center gap-1 rounded-md px-2 py-1 font-mono text-[10px]"
            style="color: var(--ink-400);"
            title="Annuler la décision sur ce crop"
            @click="clearDecision(activeAssetId)"
          >
            <RotateCcw class="h-3 w-3" /> Annuler
          </button>
        </div>

        <div class="flex-1 mx-4">
          <div class="h-1 overflow-hidden" style="background: var(--surface-2);">
            <div class="h-full transition-all duration-300" :style="{
              width: totalActionable ? `${(decidedCount / totalActionable) * 100}%` : '0%',
              background: 'linear-gradient(90deg, var(--gold-600), var(--gold-500))',
            }"></div>
          </div>
          <p class="mt-1.5 font-mono text-[10px]" style="color: var(--ink-400);">
            <kbd>J</kbd>/<kbd>K</kbd> crop · <kbd>←</kbd>/<kbd>→</kbd> raw · <kbd>1-5</kbd> focus · <kbd>⏎</kbd> valider · <kbd>E</kbd> recadrer · <kbd>F</kbd> free · <kbd>D</kbd> détections · <kbd>?</kbd> aide
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
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">← / →</dt>
          <dd style="color: var(--ink-500);">Raw suivant / précédent (multi-image)</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">1 – 5</dt>
          <dd style="color: var(--ink-500);">Focus le candidat Top N du crop actif</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">⏎</dt>
          <dd style="color: var(--ink-500);">Valider crop (assigne focused + advance) ou submit listing si tout décidé</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">F</dt>
          <dd style="color: var(--ink-500);">Sélection libre (FreeSelectorPanel inline)</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">R</dt>
          <dd style="color: var(--ink-500);">Rejeter le crop actif (raison <em>other</em>) + advance</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">N</dt>
          <dd style="color: var(--ink-500);">Skip le crop actif + advance</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">O / V / U</dt>
          <dd style="color: var(--ink-500);">Face : avers / revers / inconnu (sur assign)</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">E</dt>
          <dd style="color: var(--ink-500);">Recadrer le crop actif (éditeur de cercle sur le raw)</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">D</dt>
          <dd style="color: var(--ink-500);">Toggle examination plate (raw + cercles)</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">S</dt>
          <dd style="color: var(--ink-500);">Pas un lot → requalifier le listing en single</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">Esc</dt>
          <dd style="color: var(--ink-500);">Fermer overlay / quitter mode free / page</dd>
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

    <!-- ═══ Éditeur de re-crop manuel (overlay) — touche E ═══ -->
    <CircleCropEditor
      v-if="showCropEditor && activeCrop?.crop.review_id"
      :review-id="activeCrop.crop.review_id"
      @close="showCropEditor = false"
      @saved="onCropSaved"
    />

    <!-- ═══ Éditeur add-crop (overlay) — "+ Crop manuel" / cercle écarté ═══ -->
    <CircleCropEditor
      v-if="showAddCrop && addCropContext"
      :add-context="addCropContext"
      @close="showAddCrop = false; addCropCircle = null"
      @created="onCropCreated"
    />

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
