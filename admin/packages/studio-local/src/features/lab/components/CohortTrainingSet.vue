<script setup lang="ts">
/**
 * « Jeu d'entraînement » par classe — le maillon INSPECT de la boucle
 * d'amélioration (docs/work-in-progress/improvement-loop/04-jeu-entrainement-handoff.md).
 *
 * Ce n'est PAS de la QA : c'est le PRODUIT = le set exact de crops eBay reviewés
 * qui part réellement à l'entraînement, classe par classe. Les classes sont
 * rangées « à inspecter d'abord » (R@1 studio croissant), les crops « suspect
 * d'abord » (face ≠ obverse, qualité basse). Trois actions par crop :
 *   - clic     → inclure / exclure du train (réversible, effet au re-bake).
 *   - recadrer → CircleCropEditor en place (un crop moche mais bien classé se
 *                re-croppe plutôt que de s'exclure).
 *   - réassigner → rediriger un intrus vers la bonne classe (eurio_id).
 */
import DrawerSection from '@/features/lab/components/DrawerSection.vue'
import CircleCropEditor from '@/features/review/components/CircleCropEditor.vue'
import CoinHoverPreview from '@/features/review/components/CoinHoverPreview.vue'
import DinoSuggestions from '@/features/review/components/DinoSuggestions.vue'
import FreeSelectorPanel from '@/features/review/components/FreeSelectorPanel.vue'
import type { DinoSuggestion } from '@/features/review/composables/useDinoSuggestions'
import { recomputeDinoSuggestionsByAssetId } from '@/features/review/composables/useDinoSuggestions'
import type { CoinSearchEntry } from '@/features/review/composables/useCoinsSearch'
import { ML_API } from '@/features/training/composables/useTrainingApi'
import {
  LAB_KEYS,
  useCohortTrainingCropsQuery,
  useSetTrainingEligibleMutation,
  useReassignAssetMutation,
  useReopenReviewMutation,
  useAcceptTrainingMutation,
  useDismissIntruderMutation,
  useStartTrainingScanMutation,
  useTrainingScanStatusQuery,
} from '@/features/lab/composables/useLabQueries'
import type { DrawerState, TrainingCrop, TrainingCropClass } from '@/features/lab/types'
import { useQueryClient } from '@tanstack/vue-query'
import {
  AlertTriangle, ArrowRightLeft, Check, ChevronLeft, ChevronRight, Crop, Loader2,
  Minus, Plus, RefreshCw, ScanSearch, Undo2, X,
} from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'

const props = defineProps<{ cohortId: string }>()
const cohortId = computed(() => props.cohortId)

const query = useCohortTrainingCropsQuery(cohortId)
const toggle = useSetTrainingEligibleMutation(cohortId)
const reassign = useReassignAssetMutation(cohortId)
const reopenReview = useReopenReviewMutation(cohortId)
const acceptTraining = useAcceptTrainingMutation(cohortId)
const dismissIntruder = useDismissIntruderMutation(cohortId)

// « Faux positif — garde-le au train » : override en 1 clic du badge intrus,
// sans ouvrir la modale ni changer de classe (le crop reste éligible tel quel).
function onDismissIntruder(c: TrainingCrop) {
  if (dismissIntruder.isPending.value) return
  dismissIntruder.mutate({ assetId: c.asset_id })
}

const classes = computed<TrainingCropClass[]>(() => query.data.value?.classes ?? [])

// ─── Ordre d'affichage figé pour la session (fix tri instable) ────────────
// Le serveur trie les classes par (R@1, −n_intruders, −n_unknown_face) : dès
// qu'on réassigne / dismisse un intrus, `n_intruders` baisse → la clé change →
// la classe SAUTE de place au refetch, pendant qu'on édite dessus. On capture
// l'ordre au premier chargement et on le GARDE stable : le serveur peut
// re-trier comme il veut, l'écran ne bouge plus sous les doigts. Les nouvelles
// classes s'ajoutent en fin (dans l'ordre serveur) ; celles qui disparaissent
// sortent naturellement. Réinitialisé quand on change de cohorte.
const classOrder = ref<string[]>([])
watch(cohortId, () => { classOrder.value = [] })
watch(
  classes,
  (list) => {
    if (!list.length) return
    const known = new Set(classOrder.value)
    const additions = list.map((c) => c.class_id).filter((id) => !known.has(id))
    if (additions.length) classOrder.value = [...classOrder.value, ...additions]
  },
  { immediate: true },
)
const orderedClasses = computed<TrainingCropClass[]>(() => {
  const idx = new Map(classOrder.value.map((id, i) => [id, i]))
  return [...classes.value].sort(
    (a, b) => (idx.get(a.class_id) ?? Infinity) - (idx.get(b.class_id) ?? Infinity),
  )
})

const totalEligible = computed(() =>
  classes.value.reduce((s, c) => s + c.n_eligible, 0),
)
const totalSuspect = computed(() =>
  classes.value.reduce((s, c) => s + c.n_unknown_face, 0),
)
const totalIntruders = computed(() =>
  classes.value.reduce((s, c) => s + c.n_intruders, 0),
)
// Auto-ouvre quand il y a quelque chose à inspecter (intrus, suspects, R@1 bas).
const needsAttention = computed(() =>
  classes.value.some((c) =>
    c.n_intruders > 0 || c.n_unknown_face > 0 || (c.r_at_1 != null && c.r_at_1 < 0.8),
  ),
)
const state = computed<DrawerState>(() => {
  if (query.isLoading.value || !classes.value.length) return 'empty'
  return needsAttention.value ? 'partial' : 'ready'
})
const summary = computed(() => {
  if (query.isLoading.value) return 'chargement…'
  if (!classes.value.length) return 'pas de crops'
  return `${classes.value.length} classes · ${totalEligible.value} dans le train`
    + (totalIntruders.value ? ` · ${totalIntruders.value} à vérifier` : '')
    + (totalSuspect.value ? ` · ${totalSuspect.value} faces ?` : '')
})

// ─── Scan Dino (P1 intrus + P2 face) ──────────────────────────────────────
// Subprocess détaché côté ML : on lance, le statut se poll (2 s), et à la
// clôture on invalide training-crops pour merger badges intrus + faces.
const qc = useQueryClient()
const scanStatus = useTrainingScanStatusQuery(cohortId)
const startScan = useStartTrainingScanMutation(cohortId)
const scanRunning = computed(() => scanStatus.data.value?.status === 'running')
watch(
  () => scanStatus.data.value?.status,
  (now, before) => {
    if (before === 'running' && (now === 'done' || now === 'failed')) {
      qc.invalidateQueries({ queryKey: LAB_KEYS.trainingCrops(cohortId.value) })
    }
  },
)
const scanProgress = computed(() => {
  const s = scanStatus.data.value
  if (!s || s.status !== 'running') return null
  return s.n_total ? `${s.n_done ?? 0}/${s.n_total}` : `${s.n_done ?? 0}`
})
// Dernier scan terminé (mergé dans training-crops) — fraîcheur des badges.
const lastScan = computed(() => query.data.value?.scan ?? null)
const scanFailed = computed(() => scanStatus.data.value?.status === 'failed')

function launchScan() {
  if (scanRunning.value || startScan.isPending.value) return
  startScan.mutate()
}

// ─── Δ R@1 (P5) + santé (P4) + confusions (P6) — helpers d'affichage ──────
const minReal = computed(() => query.data.value?.min_real ?? 10)

function deltaLabel(c: TrainingCropClass): string | null {
  if (c.r_at_1_delta == null) return null
  const pts = c.r_at_1_delta * 100
  return `${pts >= 0 ? '+' : ''}${pts.toFixed(0)} pt${Math.abs(pts) >= 2 ? 's' : ''}`
}
function deltaColor(c: TrainingCropClass): string {
  const d = c.r_at_1_delta ?? 0
  if (d > 0.005) return 'var(--success)'
  if (d < -0.005) return 'var(--danger)'
  return 'var(--ink-400)'
}
function deltaTitle(c: TrainingCropClass): string {
  const prev = c.r_at_1_prev != null ? (c.r_at_1_prev * 100).toFixed(0) + '%' : '—'
  const cur = c.r_at_1 != null ? (c.r_at_1 * 100).toFixed(0) + '%' : '—'
  let seeds = ''
  if (c.n_real_prev_bake != null || c.n_real_last_bake != null) {
    seeds = `\nseed réel au bake : ${c.n_real_prev_bake ?? '—'} → ${c.n_real_last_bake ?? '—'}`
    + (c.n_real_last_bake != null && c.n_eligible !== c.n_real_last_bake
      ? ` (maintenant ${c.n_eligible} — re-bake pour appliquer)` : '')
  }
  return `R@1 : ${prev} → ${cur} (vs itération benchée précédente)${seeds}`
}

function healthTitle(c: TrainingCropClass): string {
  return [
    `${c.n_obverse} obverse confirmés · ${c.n_unknown_face} face à confirmer`
    + (c.n_reverse_flagged ? ` · ${c.n_reverse_flagged} reverse (hors bake)` : ''),
    `avers Numista : ${c.has_numista_ref ? 'présent' : 'ABSENT'} · réfs BCE/JO : ${c.n_bce_ref}`,
    c.underfed
      ? `sous-alimentée : ${c.n_eligible} < ${minReal.value} crops réels — sourcer (scrape/rescue)`
      : `prête : ≥ ${minReal.value} crops réels`,
  ].join('\n')
}

// P6 · clic sur « se confond avec X » → ouvre + scrolle la classe cible.
function jumpToClass(classId: string) {
  open[classId] = true
  requestAnimationFrame(() => {
    document.getElementById(`ts-class-${classId}`)
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  })
}

// Ouvert par défaut quand la classe mérite l'œil : intrus, R@1 bas, faces ?.
const open = reactive<Record<string, boolean>>({})
function isOpen(c: TrainingCropClass): boolean {
  return open[c.class_id]
    ?? (c.n_intruders > 0
      || (c.r_at_1 != null && c.r_at_1 < 0.8)
      || c.n_unknown_face > 0)
}
function toggleOpen(c: TrainingCropClass) {
  open[c.class_id] = !isOpen(c)
}

// ─── Entonnoir de tri (funnel) — spec UX validé PO 2026-07-03 ─────────────
// Chaque classe expose des LISTES par état, pliables, du MOINS filtré (en tête)
// au PLUS filtré (Au train, en bas). Catégories DISJOINTES (un crop = une
// liste), 5 seules. « Intrus » n'est plus une catégorie : le doute Dino vit
// dans la worklist « À vérifier ». « Reverse » et « Face ? » n'existent plus :
// un revers = non attribuable (côté commun) → « Rejetées » ; une face non
// étiquetée reste « Au train » (le scan la résout, anneau pointillé).
type CategoryKey = 'verify' | 'review' | 'rejected' | 'excluded' | 'train'

const CATEGORY_DEFS: { key: CategoryKey; label: string; title: string }[] = [
  { key: 'verify', label: 'À vérifier', title: 'Le scan Dino a un doute — à trancher (réassigner / rejeter / exclure)' },
  { key: 'review', label: 'À reviewer', title: 'Jamais jugées (needs_review) — en attente de review' },
  { key: 'rejected', label: 'Rejetées', title: 'Pas cette pièce (cent, 1 €, pas une pièce, revers) — déchet' },
  { key: 'excluded', label: 'Exclues', title: 'Bonne pièce, image inutilisable (flou, tilt, peinture) — hors train, réversible' },
  { key: 'train', label: 'Au train', title: 'Validées — partent au modèle' },
]

// Priorité DISJOINTE : le doute Dino prime (worklist d'action) ; puis rejeté OU
// revers (revers = non attribuable → rejeté) ; puis needs_review ; puis exclu ;
// sinon au train (avers OU face non étiquetée, résolue par le scan).
function cropCategory(c: TrainingCrop): CategoryKey {
  if (c.intruder_suspect) return 'verify'
  if (c.resolution_status === 'rejected' || c.face === 'reverse') return 'rejected'
  if (c.resolution_status === 'needs_review') return 'review'
  if (!c.training_eligible) return 'excluded'
  return 'train'
}

interface CategoryGroup {
  key: CategoryKey
  label: string
  title: string
  crops: TrainingCrop[]
}
function groupedCrops(cls: TrainingCropClass): CategoryGroup[] {
  const buckets = new Map<CategoryKey, TrainingCrop[]>()
  for (const crop of cls.crops) {
    const k = cropCategory(crop)
    const b = buckets.get(k)
    if (b) b.push(crop)
    else buckets.set(k, [crop])
  }
  return CATEGORY_DEFS
    .filter((d) => buckets.has(d.key))
    .map((d) => ({ ...d, crops: buckets.get(d.key)! }))
}

// Pliage par (classe, catégorie). Défaut : « Intrus ? » ouvert (c'est la liste
// d'actions), le reste plié — on déplie ce qu'on veut inspecter.
const groupOpen = reactive<Record<string, boolean>>({})
function isGroupOpen(cls: TrainingCropClass, key: CategoryKey): boolean {
  return groupOpen[`${cls.class_id}:${key}`] ?? (key === 'verify')
}
function toggleGroup(cls: TrainingCropClass, key: CategoryKey) {
  groupOpen[`${cls.class_id}:${key}`] = !isGroupOpen(cls, key)
}
function groupCountColor(key: CategoryKey): string {
  if (key === 'verify') return 'var(--indigo-700)'
  if (key === 'rejected') return 'var(--danger)'
  if (key === 'excluded') return 'var(--warning)'
  if (key === 'train') return 'var(--success)'
  return 'var(--ink-400)'
}

// Overlay d'état honnête (le « exclu » unique mentait : 52/108 étaient juste
// en attente de review) — rien pour les crops au train.
function stateLabel(c: TrainingCrop): string | null {
  if (c.resolution_status === 'rejected') return 'rejetée'
  if (c.face === 'reverse') return 'revers → rejetée'
  if (c.resolution_status === 'needs_review') return 'à reviewer'
  if (!c.training_eligible) return 'exclue'
  return null
}

// ─── Zoom au survol (retour PO : 64 px illisible) ─────────────────────────
// Vignettes 112 px + preview flottante 220 px (même brique que la review).
const hoverCrop = ref<TrainingCrop | null>(null)
const hoverRect = ref<DOMRect | null>(null)
function onTileEnter(c: TrainingCrop, e: MouseEvent) {
  const target = e.currentTarget as HTMLElement | null
  if (!target) return
  hoverCrop.value = c
  hoverRect.value = target.getBoundingClientRect()
}
function onTileLeave(c: TrainingCrop) {
  if (hoverCrop.value?.asset_id === c.asset_id) {
    hoverCrop.value = null
    hoverRect.value = null
  }
}
const hoverLabel = computed(() => {
  const c = hoverCrop.value
  if (!c) return null
  const bits = [
    stateLabel(c) ?? 'au train',
    `face ${c.face ?? '?'}`,
    c.intruder_suspect ? '⚠ intrus ?' : null,
  ]
  return bits.filter(Boolean).join(' · ')
})

function r1Color(r: number | null): string {
  if (r == null) return 'var(--ink-400)'
  if (r < 0.5) return 'var(--danger)'
  if (r < 0.8) return 'var(--warning)'
  return 'var(--success)'
}
function r1Label(r: number | null): string {
  return r == null ? '—' : (r * 100).toFixed(0) + '%'
}
function r1Title(r: number | null): string {
  return r == null
    ? 'Pas de benchmark récent — cette classe n’a pas encore été évaluée'
    : 'R@1 studio (dernière itération)'
}

// Cache-bust par asset : après un re-crop la vignette pointe le même URL, on
// force le navigateur à recharger l'image via `?v=`.
const bust = reactive<Record<string, number>>({})
function imgUrl(c: TrainingCrop): string {
  const v = bust[c.asset_id]
  return `${ML_API}${c.file_url}${v ? `?v=${v}` : ''}`
}

/**
 * Anneau — l'état encode la valeur d'entraînement du crop, PAS la netteté :
 *  - rouge (danger)        = rejeté / non-2€ / revers → « Rejetées » (un revers
 *                            = côté carte commun, non attribuable → déchet)
 *  - vert plein (success)  = éligible + face obverse confirmée → part au train
 *  - pointillés neutres    = éligible mais face NON DÉTECTÉE (unknown) → part au
 *                            train, face à confirmer (le classifieur ne l'a pas
 *                            étiquetée ; ce n'est pas un défaut de crop)
 *  - gris plein (surface-3) = propre mais exclu du train
 */
function isUnverifiedFace(c: TrainingCrop): boolean {
  return c.training_eligible
    && c.face !== 'obverse' && c.face !== 'reverse'
    && c.resolution_status !== 'rejected' && c.denom !== 'not_2eur'
}
function ringColor(c: TrainingCrop): string {
  // Revers rangé avec les rejetés (rouge) — cohérent avec cropCategory + la
  // légende funnel : non attribuable depuis le côté commun.
  if (c.resolution_status === 'rejected' || c.denom === 'not_2eur' || c.face === 'reverse')
    return 'var(--danger)'
  if (c.training_eligible && c.face === 'obverse') return 'var(--success)'
  if (isUnverifiedFace(c)) return 'var(--ink-400)'
  return 'var(--surface-3)'
}
function ringOutline(c: TrainingCrop): string {
  return `2px ${isUnverifiedFace(c) ? 'dashed' : 'solid'} ${ringColor(c)}`
}

// Exclure / réinclure (le geste de tri fréquent) — porté par un petit bouton
// SUR l'encadré (plus par le clic sur l'image, désormais réservé au carousel).
const canToggle = (c: TrainingCrop) => c.resolution_status !== 'rejected'
function onExcludeToggle(c: TrainingCrop) {
  if (!canToggle(c)) return
  toggle.mutate({ assetId: c.asset_id, eligible: !c.training_eligible })
}

// Bouton « train » de l'encadré. Sur un crop NEEDS_REVIEW, un simple flip
// d'éligibilité ne le sort pas de « À reviewer » (le classement met
// needs_review avant l'éligibilité) → il faut une VRAIE décision de review :
// « accepter au train » (manual + eligible). Sur un crop déjà tranché, c'est le
// flip d'éligibilité habituel (retirer / remettre au train).
const isPendingReview = (c: TrainingCrop) => c.resolution_status === 'needs_review'
// Affiche « − » (retirer) seulement pour un crop tranché ET actuellement au
// train ; sinon « + » (accepter / remettre au train).
const showsMinus = (c: TrainingCrop) => !isPendingReview(c) && c.training_eligible
function trainBtnTitle(c: TrainingCrop): string {
  if (isPendingReview(c)) return 'Accepter au train (valide la review)'
  return c.training_eligible ? 'Retirer du train' : 'Remettre au train'
}
function onTrainAction(c: TrainingCrop) {
  if (!canToggle(c)) return
  if (isPendingReview(c)) {
    if (!acceptTraining.isPending.value) acceptTraining.mutate({ assetId: c.asset_id })
  } else {
    onExcludeToggle(c)
  }
}

// « Repasser en reviewer » : renvoie un crop tranché (au train ou exclu) dans
// la file de review vivante. Pas pour les needs_review (déjà en review) ni les
// rejetés (restaurables côté review, autre chemin).
const canReopen = (c: TrainingCrop) =>
  c.resolution_status !== 'needs_review' && c.resolution_status !== 'rejected'
function onReopenReview(c: TrainingCrop) {
  if (!canReopen(c) || reopenReview.isPending.value) return
  reopenReview.mutate({ assetId: c.asset_id })
}

// Le badge dit POURQUOI (deux signaux du scan) : 'margin' = une autre classe
// de la cohorte le réclame ; 'outlier' = il ne ressemble pas à ses camarades
// (vraie classe probablement hors cohorte — cas Brandenburg).
function intruderReasonText(c: TrainingCrop): string {
  const reason = c.intruder_reason ?? 'margin'
  const bits: string[] = []
  if (reason.includes('margin') && c.intruder_top1_class) {
    bits.push(
      `Dino préfère ${c.intruder_top1_class}`
      + (c.intruder_margin != null ? ` (marge +${c.intruder_margin.toFixed(3)})` : ''),
    )
  }
  if (reason.includes('outlier')) {
    bits.push('ne ressemble pas à ses camarades de classe (outlier)')
  }
  return bits.join(' · ')
}

function cropTitle(c: TrainingCrop): string {
  const q = c.quality_score != null ? c.quality_score.toFixed(2) : '—'
  const inout = stateLabel(c) ?? 'au train'
  const intr = c.intruder_suspect
    ? `\n⚠ probable intrus — ${intruderReasonText(c)}` : ''
  return `${c.eurio_id}\nface: ${c.face ?? '∅'} · denom: ${c.denom ?? '∅'} · qualité: ${q}\nstatut: ${c.resolution_status} · ${inout}${intr}\n(clic pour ${c.training_eligible ? 'exclure' : 'réinclure'})`
}

function intruderTitle(c: TrainingCrop): string {
  return `Probable intrus : ${intruderReasonText(c)}\nClic : réassigner à la bonne classe`
}

// ─── Recrop en place (§5) ─────────────────────────────────────────────────
const recropAssetId = ref<string | null>(null)
function openRecrop(c: TrainingCrop) {
  recropAssetId.value = c.asset_id
}
function onRecropSaved() {
  const id = recropAssetId.value
  if (id) bust[id] = (bust[id] ?? 0) + 1
  recropAssetId.value = null
}

// ─── Réassignation à la bonne classe (§6) ─────────────────────────────────
// On réutilise les briques de la review : suggestions Dino (DinoSuggestions,
// keyé asset) + sélecteur libre cascade/fuzzy (FreeSelectorPanel). Un clic sur
// l'une OU l'autre réassigne directement (comme en review) puis referme.
const reassignCrop = ref<TrainingCrop | null>(null)
const reassignError = ref<string | null>(null)
// Bumpé après « recalculer Dino » → force DinoSuggestions à refetcher.
const dinoReloadKey = ref(0)
const dinoRecomputing = ref(false)

function openReassign(c: TrainingCrop) {
  reassignCrop.value = c
  reassignError.value = null
}
function closeReassign() {
  reassignCrop.value = null
  reassignError.value = null
}

function doReassign(eurioId: string) {
  const crop = reassignCrop.value
  if (!crop || reassign.isPending.value) return
  // Réassigner vers la MÊME classe = « le choix Dino était faux, garde-le » :
  // on laisse passer (le backend périme le verdict intrus). Plus de no-op muet.
  reassignError.value = null
  reassign.mutate(
    { assetId: crop.asset_id, eurioId },
    {
      onSuccess: closeReassign,
      onError: (e) => {
        reassignError.value = e instanceof Error ? e.message : String(e)
      },
    },
  )
}
const onDinoSelect = (s: DinoSuggestion) => doReassign(s.eurio_id)
const onFreeSelect = (entry: CoinSearchEntry) => doReassign(entry.eurio_id)

async function recomputeDino() {
  const crop = reassignCrop.value
  if (!crop || dinoRecomputing.value) return
  dinoRecomputing.value = true
  try {
    await recomputeDinoSuggestionsByAssetId(crop.asset_id)
    dinoReloadKey.value += 1 // refetch DinoSuggestions sur la version fraîche
  } finally {
    dinoRecomputing.value = false
  }
}

// ─── Carousel plein écran (inspection « une à une ») ──────────────────────
// Clic sur une vignette → ouvre la pièce EN GRAND ; flèches ←/→ (clavier ou
// boutons flanquant l'image, HORS de la pièce) pour défiler la SOUS-LISTE
// courante (ex. tous les « Au train » de la classe), compteur « n / total ».
// On mémorise les asset_ids (ordre stable) + l'index, et on relit le crop VIVANT
// par id dans le cache : exclure/réinclure met à jour l'affichage sans faire
// sortir la pièce du carousel (on reste en train d'inspecter).
const cropById = computed(() => {
  const m = new Map<string, TrainingCrop>()
  for (const cls of classes.value)
    for (const cr of cls.crops) m.set(cr.asset_id, cr)
  return m
})

const carousel = ref<{ assetIds: string[]; index: number; label: string } | null>(null)
function openCarousel(crops: TrainingCrop[], index: number, label: string) {
  // Le carousel couvre l'écran → le mouseleave de la vignette ne partira pas ;
  // on éteint la preview flottante (z-60) pour ne pas la laisser au-dessus.
  hoverCrop.value = null
  hoverRect.value = null
  carousel.value = { assetIds: crops.map((c) => c.asset_id), index, label }
}
function closeCarousel() {
  carousel.value = null
}
const carouselCrop = computed<TrainingCrop | null>(() => {
  const c = carousel.value
  if (!c) return null
  return cropById.value.get(c.assetIds[c.index]) ?? null
})
function carouselPrev() {
  if (carousel.value && carousel.value.index > 0) carousel.value.index -= 1
}
function carouselNext() {
  if (carousel.value && carousel.value.index < carousel.value.assetIds.length - 1)
    carousel.value.index += 1
}

// Flèches clavier ←/→ pour défiler, Échap pour fermer — inactif quand une modale
// (réassigner / recadrer) est ouverte PAR-DESSUS le carousel.
function onCarouselKey(e: KeyboardEvent) {
  if (!carousel.value || reassignCrop.value || recropAssetId.value) return
  if (e.key === 'ArrowLeft') { e.preventDefault(); carouselPrev() }
  else if (e.key === 'ArrowRight') { e.preventDefault(); carouselNext() }
  else if (e.key === 'Escape') { e.preventDefault(); closeCarousel() }
}
onMounted(() => window.addEventListener('keydown', onCarouselKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onCarouselKey))
</script>

<template>
  <DrawerSection
    number="C6"
    title="Jeu d'entraînement"
    :state="state"
    :summary="summary"
  >
    <template #body>
    <p class="mb-3 text-xs" style="color: var(--ink-400);">
      <span style="color: var(--ink-200);">Cette liste est le jeu exact qui part
      au modèle</span> — les crops eBay, classe par classe, rangées « à
      inspecter d'abord » (R@1 le plus bas en tête). Dans chaque classe, un
      entonnoir du moins filtré au plus filtré : À vérifier (le doute Dino,
      déplié — c'est la liste d'actions), À reviewer, Rejetées (pas cette
      pièce : cent, 1 €, revers), Exclues (bonne pièce, image inutilisable),
      Au train. Clic sur une vignette = l'agrandir dans le carousel (flèches
      ←/→ pour défiler la liste) ; bouton − / + sur l'encadré = retirer /
      remettre au train (réversible, effet au prochain re-bake) ; au survol :
      recadrer, réassigner, repasser en reviewer.
    </p>

    <!-- Scan Dino (P1 intrus + P2 face) : lance en arrière-plan, poll, merge. -->
    <div
      class="mb-3 flex flex-wrap items-center gap-3 rounded-lg border px-3 py-2"
      style="border-color: var(--surface-3); background: var(--surface-1);"
    >
      <button
        type="button"
        class="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium"
        style="border-color: var(--surface-3); color: var(--ink-200); background: var(--surface);"
        :disabled="scanRunning || startScan.isPending.value"
        title="Pour chaque crop éligible : détection d'intrus (Dino ensemble fermé sur les classes de la cohorte) + résolution des faces non étiquetées. N'exclut ni ne réassigne rien tout seul."
        @click="launchScan"
      >
        <Loader2 v-if="scanRunning || startScan.isPending.value" class="h-3.5 w-3.5 animate-spin" />
        <ScanSearch v-else class="h-3.5 w-3.5" />
        {{ scanRunning ? `Scan en cours… ${scanProgress ?? ''}` : 'Scanner intrus + faces (Dino)' }}
      </button>
      <span v-if="lastScan && !scanRunning" class="text-[11px]" style="color: var(--ink-400);">
        Dernier scan : {{ lastScan.n_intruders }} intrus ·
        {{ lastScan.n_faces_written }} faces résolues
        <template v-if="lastScan.finished_at"> · {{ lastScan.finished_at }}</template>
      </span>
      <span v-else-if="!lastScan && !scanRunning" class="text-[11px]" style="color: var(--ink-400);">
        Jamais scanné — lance le scan pour repérer les intrus et confirmer les faces.
      </span>
      <span
        v-if="scanFailed"
        class="text-[11px]"
        style="color: var(--danger);"
        :title="scanStatus.data.value?.error ?? undefined"
      >
        Dernier scan en échec — relancer (détail au survol).
      </span>
    </div>

    <div
      v-if="query.isLoading.value"
      class="flex items-center gap-2 rounded-lg border p-4 text-sm"
      style="border-color: var(--surface-3); color: var(--ink-400);"
    >
      <Loader2 class="h-4 w-4 animate-spin" /> Chargement…
    </div>

    <div
      v-else-if="query.isError.value"
      class="rounded-lg border p-4 text-sm"
      style="border-color: var(--surface-3); color: var(--danger);"
    >
      Erreur de chargement : {{ (query.error.value as Error)?.message }}
    </div>

    <div v-else class="space-y-2">
      <div
        v-for="c in orderedClasses"
        :id="`ts-class-${c.class_id}`"
        :key="c.class_id"
        class="rounded-lg border"
        style="border-color: var(--surface-3); background: var(--surface);"
      >
        <!-- En-tête de classe (cliquable) -->
        <button
          type="button"
          class="flex w-full items-center gap-3 px-3 py-2.5 text-left"
          @click="toggleOpen(c)"
        >
          <ChevronRight
            class="h-4 w-4 shrink-0 transition-transform"
            :style="{ transform: isOpen(c) ? 'rotate(90deg)' : 'none', color: 'var(--ink-400)' }"
          />
          <span class="font-mono text-xs" style="color: var(--ink-200);">{{ c.class_id }}</span>
          <!-- P4 · santé : sous-alimentée → sourcer, pas seulement retirer. -->
          <span
            v-if="c.underfed"
            class="rounded-md px-1.5 py-0.5 text-[10px] font-medium"
            style="background: color-mix(in srgb, var(--warning) 18%, transparent); color: var(--warning);"
            :title="healthTitle(c)"
          >sous-alimentée</span>
          <span class="ml-auto flex items-center gap-3 text-xs" style="color: var(--ink-400);">
            <!-- Worklist « À vérifier » : les doutes levés par le scan Dino -->
            <span
              v-if="c.n_intruders > 0"
              class="inline-flex items-center gap-1 font-medium"
              style="color: var(--indigo-700);"
              title="À vérifier — doutes du scan Dino, remontés en tête"
            >
              <AlertTriangle class="h-3 w-3" />{{ c.n_intruders }} à vérifier
            </span>
            <span :title="healthTitle(c)">{{ c.n_eligible }} au train</span>
            <span
              v-if="c.n_unknown_face > 0"
              style="color: var(--ink-400);"
              title="Éligibles dont la face n'est pas étiquetée — le scan les résout"
            >
              {{ c.n_unknown_face }} face ?
            </span>
            <span
              v-if="c.n_reverse_flagged > 0"
              style="color: var(--warning);"
              title="Éligibles face=reverse — hors bake (côté carte commun)"
            >
              {{ c.n_reverse_flagged }} rev
            </span>
            <span v-if="c.n_rejected > 0">{{ c.n_rejected }} rej</span>
            <!-- P5 · Δ vs itération benchée précédente -->
            <span
              v-if="deltaLabel(c)"
              class="font-semibold"
              :style="{ color: deltaColor(c) }"
              :title="deltaTitle(c)"
            >Δ {{ deltaLabel(c) }}</span>
            <span
              class="inline-flex min-w-[2.75rem] justify-center rounded-md px-1.5 py-0.5 font-semibold"
              :style="{ background: r1Color(c.r_at_1), color: c.r_at_1 == null ? 'var(--surface)' : '#fff' }"
              :title="r1Title(c.r_at_1)"
            >R@1 {{ r1Label(c.r_at_1) }}</span>
          </span>
        </button>

        <!-- Grille de crops -->
        <div v-if="isOpen(c)" class="border-t px-3 py-3" style="border-color: var(--surface-3);">
          <!-- P6 · confusions du dernier bench : où cette classe perd ses photos. -->
          <p
            v-if="c.confused_with.length"
            class="mb-2 flex flex-wrap items-center gap-1.5 text-[11px]"
            style="color: var(--ink-400);"
          >
            <span>Au bench, se confond avec :</span>
            <button
              v-for="cf in c.confused_with"
              :key="cf.class_id"
              type="button"
              class="rounded-md border px-1.5 py-0.5 font-mono text-[10px]"
              style="border-color: var(--surface-3); color: var(--ink-200); background: var(--surface-1);"
              :title="`${cf.n} photo(s) de ${c.class_id} prédite(s) ${cf.class_id} au dernier bench — clic : voir cette classe`"
              @click="jumpToClass(cf.class_id)"
            >
              ↔ {{ cf.class_id }} ({{ cf.n }})
            </button>
          </p>
          <p v-if="!c.crops.length" class="text-xs" style="color: var(--ink-400);">
            Aucun crop. (classe sans données propres — sourcer ou retirer)
          </p>
          <!-- Sous-listes pliables par état (retour PO) : au train d'abord,
               puis les intrus (dépliés = liste d'actions), puis le stock. -->
          <div v-else class="space-y-1.5">
            <div
              v-for="g in groupedCrops(c)"
              :key="g.key"
              class="rounded-md border"
              style="border-color: var(--surface-3); background: var(--surface-1);"
            >
              <button
                type="button"
                class="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-xs"
                :title="g.title"
                @click="toggleGroup(c, g.key)"
              >
                <ChevronRight
                  class="h-3.5 w-3.5 shrink-0 transition-transform"
                  :style="{ transform: isGroupOpen(c, g.key) ? 'rotate(90deg)' : 'none', color: 'var(--ink-400)' }"
                />
                <span class="font-medium" :style="{ color: groupCountColor(g.key) }">
                  {{ g.label }}
                </span>
                <span style="color: var(--ink-400);">{{ g.crops.length }}</span>
                <!-- Réconciliation C4↔C5 : les needs_review non routés sont
                     bloqués (jamais enfilés → invisibles au tiroir « Review
                     crops »). C'est l'écart honnête avec « 0 à trancher ». -->
                <span
                  v-if="g.key === 'review' && c.n_review_unrouted > 0"
                  class="ml-1 rounded px-1.5 py-0.5 text-[10px] font-medium"
                  style="background: color-mix(in srgb, var(--warning) 18%, transparent); color: var(--warning);"
                  :title="`${c.n_review_unrouted} crop(s) needs_review SANS file de review ouverte — jamais enfilés, donc invisibles au tiroir « Review crops » (§C4) et jamais tranchés. C'est ce qui explique « 0 à trancher » côté C4 alors qu'il reste des pièces à reviewer ici. (À router via un scrape/routage — pas d'action ici.)`"
                >⚠ {{ c.n_review_unrouted }} non routés</span>
              </button>

              <div
                v-if="isGroupOpen(c, g.key)"
                class="flex flex-wrap gap-2 border-t px-2.5 py-2.5"
                style="border-color: var(--surface-3); background: var(--surface);"
              >
                <div
                  v-for="(crop, ci) in g.crops"
                  :key="crop.asset_id"
                  class="group relative h-32 w-32 overflow-hidden rounded-md"
                  :style="{
                    outline: ringOutline(crop),
                    outlineOffset: '-2px',
                    opacity: crop.training_eligible ? 1 : 0.9,
                  }"
                  @mouseenter="onTileEnter(crop, $event)"
                  @mouseleave="onTileLeave(crop)"
                >
                  <!-- Clic sur l'image = ouvrir le carousel (agrandir + défiler
                       la sous-liste). Exclure/réinclure passe par le bouton
                       dédié sur l'encadré (ci-dessous). Voile allégé : grayscale
                       .2 + opacity .9 (le masque plein grisait trop, retour PO). -->
                  <img
                    :src="imgUrl(crop)"
                    loading="lazy"
                    class="h-full w-full cursor-pointer object-cover"
                    :style="{ filter: crop.training_eligible ? 'none' : 'grayscale(.2)' }"
                    :title="cropTitle(crop)"
                    @click="openCarousel(g.crops, ci, g.label)"
                  />
                  <span
                    v-if="stateLabel(crop)"
                    class="pointer-events-none absolute inset-x-0 bottom-0 bg-black/45 py-0.5 text-center text-[10px] font-medium text-white"
                  >{{ stateLabel(crop) }}</span>

                  <!-- P1 · badge intrus (toujours visible) — clic = réassigner -->
                  <button
                    v-if="crop.intruder_suspect"
                    type="button"
                    class="absolute left-0 top-0 flex h-6 w-6 items-center justify-center rounded-br-md"
                    style="background: var(--danger); color: #fff;"
                    :title="intruderTitle(crop)"
                    @click.stop="openReassign(crop)"
                  >
                    <AlertTriangle class="h-3.5 w-3.5" />
                  </button>
                  <!-- « Faux positif » : sous le badge, 1 clic pour le garder au
                       train (dismiss, sans changer de classe ni exclure). -->
                  <button
                    v-if="crop.intruder_suspect"
                    type="button"
                    class="absolute left-0 top-6 flex h-6 w-6 items-center justify-center rounded-br-md"
                    style="background: var(--success); color: #fff;"
                    title="Faire passer au train (ce n'est pas un intrus)"
                    @click.stop="onDismissIntruder(crop)"
                  >
                    <Check class="h-3.5 w-3.5" />
                  </button>

                  <!-- Bouton d'action TOUJOURS visible sur l'encadré (le geste
                       de tri fréquent) : retirer / remettre au train si le crop
                       est tranché ; ACCEPTER au train (décision de review) s'il
                       est encore « à reviewer » — sinon il n'en sortirait pas. -->
                  <button
                    v-if="canToggle(crop)"
                    type="button"
                    class="absolute right-0 top-0 z-10 m-0.5 flex h-6 w-6 items-center justify-center rounded"
                    :style="{ background: showsMinus(crop) ? 'rgba(14,14,31,.72)' : 'var(--success)', color: '#fff' }"
                    :title="trainBtnTitle(crop)"
                    @click.stop="onTrainAction(crop)"
                  >
                    <Minus v-if="showsMinus(crop)" class="h-3.5 w-3.5" />
                    <Plus v-else class="h-3.5 w-3.5" />
                  </button>

                  <!-- Barre d'actions au survol (recadrer / réassigner /
                       repasser en review), à gauche du bouton exclure. -->
                  <div
                    class="pointer-events-none absolute right-8 top-0 flex gap-0.5 p-0.5 opacity-0 transition-opacity group-hover:pointer-events-auto group-hover:opacity-100"
                  >
                    <button
                      type="button"
                      class="flex h-6 w-6 items-center justify-center rounded"
                      style="background: rgba(14,14,31,.72); color: #fff;"
                      title="Recadrer ce crop"
                      @click.stop="openRecrop(crop)"
                    >
                      <Crop class="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      class="flex h-6 w-6 items-center justify-center rounded"
                      style="background: rgba(14,14,31,.72); color: #fff;"
                      title="Réassigner à la bonne classe"
                      @click.stop="openReassign(crop)"
                    >
                      <ArrowRightLeft class="h-3.5 w-3.5" />
                    </button>
                    <button
                      v-if="canReopen(crop)"
                      type="button"
                      class="flex h-6 w-6 items-center justify-center rounded"
                      style="background: rgba(14,14,31,.72); color: #fff;"
                      title="Repasser en reviewer (renvoie dans la file de review)"
                      @click.stop="onReopenReview(crop)"
                    >
                      <Undo2 class="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <p class="mt-2 text-[11px]" style="color: var(--ink-400);">
            Badge ⚠ = à vérifier (doute Dino : une autre classe le réclame ou il
            ne ressemble pas à ses camarades — clic = réassigner) · bordure
            verte = avers confirmé, part au train · rouge = rejeté (pas cette
            pièce / non-2€ / revers). R@1 « — » = pas de benchmark récent ;
            Δ = vs itération benchée précédente. Clic = agrandir (carousel) ;
            bouton − / + sur l'encadré = retirer / remettre au train ; survol =
            recadrer / réassigner / repasser en reviewer. Effet au prochain re-bake.
          </p>
        </div>
      </div>
    </div>
    </template>
  </DrawerSection>

  <!-- Zoom au survol d'une vignette (même brique flottante que la review).
       placement="side" : la carte se pose À CÔTÉ de la vignette, jamais
       par-dessus — les boutons recadrer/réassigner restent cliquables. -->
  <CoinHoverPreview
    v-if="hoverCrop && hoverRect"
    :image-url="imgUrl(hoverCrop)"
    :eurio-id="hoverCrop.eurio_id ?? '∅'"
    :label="hoverLabel"
    :anchor-rect="hoverRect"
    placement="side"
  />

  <!-- Carousel plein écran : inspection « une à une » de la sous-liste (clic sur
       une vignette). Flèches ←/→ (clavier ou boutons flanquant l'image, HORS de
       la pièce) + compteur. z-20 : SOUS la modale réassigner (z-30) et l'éditeur
       recrop (z-40), qui s'ouvrent donc par-dessus. -->
  <div
    v-if="carousel && carouselCrop"
    class="fixed inset-0 z-20 flex flex-col"
    style="background: rgba(14,14,31,.92); backdrop-filter: blur(4px);"
    @click.self="closeCarousel"
  >
    <!-- Barre haut : sous-liste + compteur + eurio_id + fermer -->
    <header
      class="flex items-center gap-3 px-5 py-3"
      style="color: var(--ink-200);"
      @click.self="closeCarousel"
    >
      <span
        class="rounded-md px-2 py-0.5 text-xs font-medium"
        style="background: var(--surface-1);"
      >{{ carousel.label }}</span>
      <span class="font-mono text-sm">{{ carousel.index + 1 }} / {{ carousel.assetIds.length }}</span>
      <span class="truncate font-mono text-xs" style="color: var(--ink-400);">
        {{ carouselCrop.eurio_id ?? '∅' }}
      </span>
      <button
        type="button"
        class="ml-auto rounded-md border p-1.5"
        style="border-color: var(--surface-3); color: var(--ink-200); background: var(--surface-1);"
        title="Fermer (Échap)"
        @click="closeCarousel"
      >
        <X class="h-4 w-4" />
      </button>
    </header>

    <!-- Corps : [◀] image [▶] — flèches à l'extérieur de la pièce -->
    <div
      class="flex min-h-0 flex-1 items-center justify-center gap-4 px-4"
      @click.self="closeCarousel"
    >
      <button
        type="button"
        class="flex h-12 w-12 shrink-0 items-center justify-center rounded-full border transition-opacity disabled:opacity-25"
        style="border-color: var(--surface-3); color: #fff; background: rgba(255,255,255,.08);"
        :disabled="carousel.index === 0"
        title="Précédent (←)"
        @click="carouselPrev"
      >
        <ChevronLeft class="h-6 w-6" />
      </button>

      <div class="flex min-h-0 flex-col items-center gap-3">
        <img
          :src="imgUrl(carouselCrop)"
          class="max-h-[64vh] max-w-[64vw] rounded-lg object-contain"
          :style="{ outline: ringOutline(carouselCrop), outlineOffset: '-2px', background: 'var(--surface-1)' }"
        />
        <p class="text-center text-xs" style="color: var(--ink-300);">
          {{ stateLabel(carouselCrop) ?? 'au train' }} · face {{ carouselCrop.face ?? '?' }}
          <template v-if="carouselCrop.quality_score != null">
            · qualité {{ carouselCrop.quality_score.toFixed(2) }}
          </template>
          <template v-if="carouselCrop.intruder_suspect">
            · <span style="color: var(--danger);">⚠ {{ intruderReasonText(carouselCrop) }}</span>
          </template>
        </p>
      </div>

      <button
        type="button"
        class="flex h-12 w-12 shrink-0 items-center justify-center rounded-full border transition-opacity disabled:opacity-25"
        style="border-color: var(--surface-3); color: #fff; background: rgba(255,255,255,.08);"
        :disabled="carousel.index >= carousel.assetIds.length - 1"
        title="Suivant (→)"
        @click="carouselNext"
      >
        <ChevronRight class="h-6 w-6" />
      </button>
    </div>

    <!-- Barre d'actions bas : mêmes gestes que la vignette, en grand. -->
    <footer class="flex flex-wrap items-center justify-center gap-2 px-4 py-4">
      <button
        v-if="canToggle(carouselCrop)"
        type="button"
        class="inline-flex items-center gap-1.5 rounded-md border px-3 py-2 text-sm font-medium"
        :style="{
          borderColor: 'var(--surface-3)',
          background: showsMinus(carouselCrop) ? 'var(--surface-1)' : 'color-mix(in srgb, var(--success) 20%, transparent)',
          color: showsMinus(carouselCrop) ? 'var(--ink-200)' : 'var(--success)',
        }"
        @click="onTrainAction(carouselCrop)"
      >
        <Minus v-if="showsMinus(carouselCrop)" class="h-4 w-4" />
        <Plus v-else class="h-4 w-4" />
        {{ trainBtnTitle(carouselCrop) }}
      </button>
      <button
        v-if="canReopen(carouselCrop)"
        type="button"
        class="inline-flex items-center gap-1.5 rounded-md border px-3 py-2 text-sm font-medium"
        style="border-color: var(--surface-3); color: var(--ink-200); background: var(--surface-1);"
        :disabled="reopenReview.isPending.value"
        title="Renvoie ce crop dans la file de review (§C4)"
        @click="onReopenReview(carouselCrop)"
      >
        <Undo2 class="h-4 w-4" /> Repasser en reviewer
      </button>
      <button
        type="button"
        class="inline-flex items-center gap-1.5 rounded-md border px-3 py-2 text-sm font-medium"
        style="border-color: var(--surface-3); color: var(--ink-200); background: var(--surface-1);"
        @click="openReassign(carouselCrop)"
      >
        <ArrowRightLeft class="h-4 w-4" /> Réassigner
      </button>
      <button
        type="button"
        class="inline-flex items-center gap-1.5 rounded-md border px-3 py-2 text-sm font-medium"
        style="border-color: var(--surface-3); color: var(--ink-200); background: var(--surface-1);"
        @click="openRecrop(carouselCrop)"
      >
        <Crop class="h-4 w-4" /> Recadrer
      </button>
    </footer>
  </div>

  <!-- Recrop en place : même éditeur que la review, keyé asset (§5). -->
  <CircleCropEditor
    v-if="recropAssetId"
    :asset-id="recropAssetId"
    @close="recropAssetId = null"
    @saved="onRecropSaved"
  />

  <!-- Réassignation d'un crop à la bonne classe (§6) — mêmes briques que la
       review : suggestions Dino + sélecteur libre. Un clic réassigne. -->
  <div
    v-if="reassignCrop"
    class="fixed inset-0 z-30 flex items-center justify-center p-6"
    style="background: rgba(14,14,31,.72); backdrop-filter: blur(4px);"
    @click.self="closeReassign"
  >
    <div
      class="flex max-h-[88vh] w-full max-w-4xl flex-col overflow-hidden rounded-lg border"
      style="border-color: var(--surface-3); background: var(--surface);"
    >
      <!-- En-tête : titre + recalcul Dino + fermer -->
      <header
        class="flex items-center gap-3 border-b px-5 py-3"
        style="border-color: var(--surface-3);"
      >
        <div class="min-w-0">
          <h3 class="font-display text-base italic font-semibold" style="color: var(--indigo-700);">
            Réassigner le crop
          </h3>
          <p class="truncate text-xs" style="color: var(--ink-400);">
            Actuellement
            <span class="font-mono" style="color: var(--ink-200);">{{ reassignCrop.eurio_id ?? '∅' }}</span>
            — clique la bonne pièce (suggestion Dino ou recherche) ; survole une
            suggestion pour la comparer au crop.
          </p>
        </div>
        <button
          type="button"
          class="ml-auto inline-flex shrink-0 items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs"
          style="border-color: var(--surface-3); color: var(--ink-500); background: var(--surface-1);"
          :disabled="dinoRecomputing"
          title="Recalculer les suggestions Dino sur ce crop"
          @click="recomputeDino"
        >
          <RefreshCw class="h-3.5 w-3.5" :class="{ 'animate-spin': dinoRecomputing }" />
          Recalculer Dino
        </button>
        <button
          type="button"
          class="shrink-0 rounded-md border p-1.5"
          style="border-color: var(--surface-3); color: var(--ink-400);"
          title="Fermer"
          @click="closeReassign"
        >
          <X class="h-3.5 w-3.5" />
        </button>
      </header>

      <!-- Corps scrollable : crop EN GRAND à gauche (sticky, retour PO — le
           48 px rendait la comparaison impossible), suggestions à droite. -->
      <div class="relative min-h-0 flex-1 overflow-y-auto px-5 py-4">
        <p
          v-if="reassignError"
          class="mb-3 rounded-md border px-3 py-2 text-xs"
          style="border-color: var(--danger); color: var(--danger);"
        >
          {{ reassignError }}
        </p>

        <div class="flex gap-5">
          <div class="w-64 shrink-0">
            <div class="sticky top-0">
              <img
                :src="imgUrl(reassignCrop)"
                class="h-64 w-64 rounded-lg object-cover"
                style="outline: 1px solid var(--surface-3); outline-offset: -1px; background: var(--surface-1);"
              />
              <p class="mt-2 text-[11px] leading-snug" style="color: var(--ink-400);">
                face {{ reassignCrop.face ?? '?' }} ·
                {{ stateLabel(reassignCrop) ?? 'au train' }}
                <template v-if="reassignCrop.intruder_suspect">
                  <br /><span style="color: var(--danger);">⚠ {{ intruderReasonText(reassignCrop) }}</span>
                </template>
              </p>
              <button
                type="button"
                class="mt-2 inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs"
                style="border-color: var(--surface-3); color: var(--ink-500); background: var(--surface-1);"
                title="Ouvrir l'éditeur de recadrage (parfois il faut les deux)"
                @click="openRecrop(reassignCrop)"
              >
                <Crop class="h-3.5 w-3.5" /> Recadrer plutôt
              </button>
            </div>
          </div>

          <div class="min-w-0 flex-1">
            <section class="mb-5">
              <p class="mb-2 font-mono text-[10px] uppercase tracking-wider" style="color: var(--indigo-700);">
                Suggestions Dino
              </p>
              <DinoSuggestions
                :asset-id="reassignCrop.asset_id"
                :reload-key="dinoReloadKey"
                @select="onDinoSelect"
              />
            </section>

            <section>
              <p class="mb-2 font-mono text-[10px] uppercase tracking-wider" style="color: var(--indigo-700);">
                Sélecteur libre
              </p>
              <FreeSelectorPanel @select="onFreeSelect" />
            </section>
          </div>
        </div>

        <!-- Voile pendant l'écriture -->
        <div
          v-if="reassign.isPending.value"
          class="absolute inset-0 flex items-center justify-center"
          style="background: color-mix(in srgb, var(--surface) 70%, transparent);"
        >
          <Loader2 class="h-6 w-6 animate-spin" style="color: var(--indigo-700);" />
        </div>
      </div>
    </div>
  </div>
</template>
