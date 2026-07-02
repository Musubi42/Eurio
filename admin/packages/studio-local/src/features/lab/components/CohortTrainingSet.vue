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
  useStartTrainingScanMutation,
  useTrainingScanStatusQuery,
} from '@/features/lab/composables/useLabQueries'
import type { DrawerState, TrainingCrop, TrainingCropClass } from '@/features/lab/types'
import { useQueryClient } from '@tanstack/vue-query'
import {
  AlertTriangle, ArrowRightLeft, ChevronRight, Crop, Loader2, RefreshCw,
  ScanSearch, X,
} from 'lucide-vue-next'
import { computed, reactive, ref, watch } from 'vue'

const props = defineProps<{ cohortId: string }>()
const cohortId = computed(() => props.cohortId)

const query = useCohortTrainingCropsQuery(cohortId)
const toggle = useSetTrainingEligibleMutation(cohortId)
const reassign = useReassignAssetMutation(cohortId)

const classes = computed<TrainingCropClass[]>(() => query.data.value?.classes ?? [])
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
    + (totalIntruders.value ? ` · ${totalIntruders.value} intrus ?` : '')
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

// ─── Filtres par état (retour PO : les 80+ gris noyaient le signal) ───────
// Un crop appartient à une ou plusieurs catégories ; il est visible si AU
// MOINS une de ses catégories est active. Défaut = « problèmes d'abord » :
// intrus + au train + face ? + reverse — le stock à reviewer / exclu / rejeté
// reste derrière ses chips (compteurs visibles).
type FilterKey =
  | 'intruder' | 'train' | 'face' | 'reverse' | 'review' | 'excluded' | 'rejected'

const FILTER_DEFS: { key: FilterKey; label: string; title: string }[] = [
  { key: 'intruder', label: '⚠ intrus', title: 'Probables intrus (scan Dino) — tous états' },
  { key: 'train', label: 'au train', title: 'Éligibles, partent au bake (face ≠ reverse)' },
  { key: 'face', label: 'face ?', title: 'Éligibles dont la face n\'est pas étiquetée — le scan les résout' },
  { key: 'reverse', label: 'reverse', title: 'Éligibles face=reverse — hors bake (côté commun)' },
  { key: 'review', label: 'à reviewer', title: 'Jamais reviewés (needs_review) — pas exclus : en attente' },
  { key: 'excluded', label: 'exclus', title: 'Écartés du train à la main (réversible, clic pour réinclure)' },
  { key: 'rejected', label: 'rejetés', title: 'Rejetés en review (déchets) — restaurables côté review' },
]
const activeFilters = reactive<Record<FilterKey, boolean>>({
  intruder: true, train: true, face: true, reverse: true,
  review: false, excluded: false, rejected: false,
})

function cropCategories(c: TrainingCrop): FilterKey[] {
  const cats: FilterKey[] = []
  if (c.intruder_suspect) cats.push('intruder')
  if (c.resolution_status === 'rejected') cats.push('rejected')
  else if (c.resolution_status === 'needs_review') cats.push('review')
  else if (!c.training_eligible) cats.push('excluded')
  if (c.training_eligible && c.face !== 'reverse') cats.push('train')
  if (c.training_eligible && (c.face == null || c.face === 'unknown')) cats.push('face')
  if (c.training_eligible && c.face === 'reverse') cats.push('reverse')
  return cats
}
function isVisible(c: TrainingCrop): boolean {
  return cropCategories(c).some((k) => activeFilters[k])
}
function visibleCrops(cls: TrainingCropClass): TrainingCrop[] {
  return cls.crops.filter(isVisible)
}
const filterCounts = computed<Record<FilterKey, number>>(() => {
  const counts = { intruder: 0, train: 0, face: 0, reverse: 0, review: 0, excluded: 0, rejected: 0 }
  for (const cls of classes.value)
    for (const crop of cls.crops)
      for (const k of cropCategories(crop)) counts[k] += 1
  return counts
})

// Overlay d'état honnête (le « exclu » unique mentait : 52/108 étaient juste
// en attente de review) — rien pour les crops au train.
function stateLabel(c: TrainingCrop): string | null {
  if (c.resolution_status === 'rejected') return 'rejeté'
  if (c.resolution_status === 'needs_review') return 'à reviewer'
  if (!c.training_eligible) return 'exclu'
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
 *  - rouge (danger)        = rejeté / non-2€ → déchet
 *  - ambre (warning)       = face = reverse → mauvaise face (côté carte commun,
 *                            identique à toutes les 2€ → nuisible à la classe)
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
  if (c.resolution_status === 'rejected' || c.denom === 'not_2eur')
    return 'var(--danger)'
  if (c.face === 'reverse') return 'var(--warning)'
  if (c.training_eligible && c.face === 'obverse') return 'var(--success)'
  if (isUnverifiedFace(c)) return 'var(--ink-400)'
  return 'var(--surface-3)'
}
function ringOutline(c: TrainingCrop): string {
  return `2px ${isUnverifiedFace(c) ? 'dashed' : 'solid'} ${ringColor(c)}`
}

const canToggle = (c: TrainingCrop) => c.resolution_status !== 'rejected'

function onCropClick(c: TrainingCrop) {
  if (!canToggle(c)) return
  toggle.mutate({ assetId: c.asset_id, eligible: !c.training_eligible })
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
  if (eurioId === crop.eurio_id) { closeReassign(); return }
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
</script>

<template>
  <DrawerSection
    number="C5"
    title="Jeu d'entraînement"
    :state="state"
    :summary="summary"
  >
    <template #body>
    <p class="mb-3 text-xs" style="color: var(--ink-400);">
      <span style="color: var(--ink-200);">Cette liste est le jeu exact qui part
      au modèle</span> — les crops eBay reviewés, classe par classe. Déjà validé
      et rangé « à inspecter d'abord » (R@1 le plus bas en tête, intrus puis
      suspects en premier). Bordure verte = part au train ; pointillés = face à
      confirmer ; ambre / rouge = à vérifier. Clic = inclure / exclure
      (réversible, effet au prochain re-bake) ; au survol : recadrer ou
      réassigner un crop.
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

    <!-- Filtres par état — défaut « problèmes d'abord », le stock (à reviewer /
         exclus / rejetés) reste derrière ses chips. -->
    <div class="mb-3 flex flex-wrap items-center gap-1.5">
      <span class="mr-1 text-[11px]" style="color: var(--ink-400);">Afficher :</span>
      <button
        v-for="f in FILTER_DEFS"
        :key="f.key"
        type="button"
        class="rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors"
        :style="activeFilters[f.key]
          ? { background: 'var(--indigo-700)', borderColor: 'var(--indigo-700)', color: 'var(--surface)' }
          : { background: 'var(--surface)', borderColor: 'var(--surface-3)', color: 'var(--ink-400)' }"
        :title="f.title"
        @click="activeFilters[f.key] = !activeFilters[f.key]"
      >
        {{ f.label }} ({{ filterCounts[f.key] }})
      </button>
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
        v-for="c in classes"
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
            <!-- P1 · intrus levés par le scan -->
            <span
              v-if="c.n_intruders > 0"
              class="inline-flex items-center gap-1 font-medium"
              style="color: var(--danger);"
              title="Probables intrus (scan Dino) — remontés en tête de grille"
            >
              <AlertTriangle class="h-3 w-3" />{{ c.n_intruders }} intrus ?
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
          <p
            v-else-if="!visibleCrops(c).length"
            class="text-xs"
            style="color: var(--ink-400);"
          >
            {{ c.crops.length }} crops masqués par les filtres (rien à voir dans
            les catégories actives — active « à reviewer » / « exclus » /
            « rejetés » pour tout voir).
          </p>
          <div v-else class="flex flex-wrap gap-2">
            <div
              v-for="crop in visibleCrops(c)"
              :key="crop.asset_id"
              class="group relative h-28 w-28 overflow-hidden rounded-md"
              :style="{
                outline: ringOutline(crop),
                outlineOffset: '-2px',
                opacity: crop.training_eligible ? 1 : 0.55,
              }"
              @mouseenter="onTileEnter(crop, $event)"
              @mouseleave="onTileLeave(crop)"
            >
              <img
                :src="imgUrl(crop)"
                loading="lazy"
                class="h-full w-full object-cover"
                :class="{ 'cursor-pointer': canToggle(crop), 'cursor-default': !canToggle(crop) }"
                :style="{ filter: crop.training_eligible ? 'none' : 'grayscale(1)' }"
                :title="cropTitle(crop)"
                @click="onCropClick(crop)"
              />
              <span
                v-if="stateLabel(crop)"
                class="pointer-events-none absolute inset-x-0 bottom-0 bg-black/60 py-0.5 text-center text-[10px] font-medium text-white"
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

              <!-- Barre d'actions au survol (recadrer / réassigner) -->
              <div
                class="absolute right-0 top-0 flex gap-0.5 p-0.5 opacity-0 transition-opacity group-hover:opacity-100"
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
              </div>
            </div>
          </div>
          <p
            v-if="c.crops.length && visibleCrops(c).length && visibleCrops(c).length < c.crops.length"
            class="mt-1.5 text-[11px]"
            style="color: var(--ink-400);"
          >
            + {{ c.crops.length - visibleCrops(c).length }} crops masqués par
            les filtres.
          </p>
          <p class="mt-2 text-[11px]" style="color: var(--ink-400);">
            Badge rouge ⚠ = probable intrus (une autre classe le réclame, ou il
            ne ressemble pas à ses camarades — clic = réassigner) · bordure
            verte = obverse confirmée, part au train · pointillés = face à
            confirmer (le scan la résout) · ambre = reverse (hors bake) · rouge
            = rejeté / non-2€ · gris = à reviewer / exclu (bandeau). R@1 « — » =
            pas de benchmark récent ; Δ = vs itération benchée précédente. Clic
            = inclure / exclure ; survol = zoom + recadrer / réassigner. Effet
            au prochain re-bake.
          </p>
        </div>
      </div>
    </div>
    </template>
  </DrawerSection>

  <!-- Zoom au survol d'une vignette (même brique flottante que la review). -->
  <CoinHoverPreview
    v-if="hoverCrop && hoverRect"
    :image-url="imgUrl(hoverCrop)"
    :eurio-id="hoverCrop.eurio_id ?? '∅'"
    :label="hoverLabel"
    :anchor-rect="hoverRect"
  />

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
