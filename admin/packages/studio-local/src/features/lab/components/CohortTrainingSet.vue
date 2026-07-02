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
import DinoSuggestions from '@/features/review/components/DinoSuggestions.vue'
import FreeSelectorPanel from '@/features/review/components/FreeSelectorPanel.vue'
import type { DinoSuggestion } from '@/features/review/composables/useDinoSuggestions'
import { recomputeDinoSuggestionsByAssetId } from '@/features/review/composables/useDinoSuggestions'
import type { CoinSearchEntry } from '@/features/review/composables/useCoinsSearch'
import { ML_API } from '@/features/training/composables/useTrainingApi'
import {
  useCohortTrainingCropsQuery,
  useSetTrainingEligibleMutation,
  useReassignAssetMutation,
} from '@/features/lab/composables/useLabQueries'
import type { DrawerState, TrainingCrop, TrainingCropClass } from '@/features/lab/types'
import { ArrowRightLeft, ChevronRight, Crop, Loader2, RefreshCw, X } from 'lucide-vue-next'
import { computed, reactive, ref } from 'vue'

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
// Auto-ouvre quand il y a quelque chose à inspecter (suspects ou R@1 imparfait).
const needsAttention = computed(() =>
  classes.value.some((c) => c.n_unknown_face > 0 || (c.r_at_1 != null && c.r_at_1 < 0.8)),
)
const state = computed<DrawerState>(() => {
  if (query.isLoading.value || !classes.value.length) return 'empty'
  return needsAttention.value ? 'partial' : 'ready'
})
const summary = computed(() => {
  if (query.isLoading.value) return 'chargement…'
  if (!classes.value.length) return 'pas de crops'
  return `${classes.value.length} classes · ${totalEligible.value} dans le train`
    + (totalSuspect.value ? ` · ${totalSuspect.value} suspects` : '')
})

// Ouvert par défaut quand la classe mérite l'œil : R@1 imparfait ou suspects.
const open = reactive<Record<string, boolean>>({})
function isOpen(c: TrainingCropClass): boolean {
  return open[c.class_id]
    ?? ((c.r_at_1 != null && c.r_at_1 < 0.8) || c.n_unknown_face > 0)
}
function toggleOpen(c: TrainingCropClass) {
  open[c.class_id] = !isOpen(c)
}

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

function cropTitle(c: TrainingCrop): string {
  const q = c.quality_score != null ? c.quality_score.toFixed(2) : '—'
  const inout = c.training_eligible ? 'dans le train' : 'exclu'
  return `${c.eurio_id}\nface: ${c.face ?? '∅'} · denom: ${c.denom ?? '∅'} · qualité: ${q}\nstatut: ${c.resolution_status} · ${inout}\n(clic pour ${c.training_eligible ? 'exclure' : 'réinclure'})`
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
      et rangé « à inspecter d'abord » (R@1 le plus bas en tête, suspects en
      premier). Bordure verte = part au train ; pointillés = face à confirmer ;
      ambre / rouge = à vérifier. Clic = inclure / exclure (réversible, effet au
      prochain re-bake) ; au survol : recadrer ou réassigner un crop.
    </p>

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
          <span class="ml-auto flex items-center gap-3 text-xs" style="color: var(--ink-400);">
            <span>{{ c.n_eligible }} elig</span>
            <span
              v-if="c.n_unknown_face > 0"
              style="color: var(--ink-400);"
              title="Éligibles dont la face n'est pas confirmée obverse (à confirmer)"
            >
              {{ c.n_unknown_face }} face ?
            </span>
            <span v-if="c.n_rejected > 0">{{ c.n_rejected }} rej</span>
            <span
              class="inline-flex min-w-[2.75rem] justify-center rounded-md px-1.5 py-0.5 font-semibold"
              :style="{ background: r1Color(c.r_at_1), color: c.r_at_1 == null ? 'var(--surface)' : '#fff' }"
              :title="r1Title(c.r_at_1)"
            >R@1 {{ r1Label(c.r_at_1) }}</span>
          </span>
        </button>

        <!-- Grille de crops -->
        <div v-if="isOpen(c)" class="border-t px-3 py-3" style="border-color: var(--surface-3);">
          <p v-if="!c.crops.length" class="text-xs" style="color: var(--ink-400);">
            Aucun crop. (classe sans données propres — sourcer ou retirer)
          </p>
          <div v-else class="flex flex-wrap gap-1.5">
            <div
              v-for="crop in c.crops"
              :key="crop.asset_id"
              class="group relative h-16 w-16 overflow-hidden rounded-md"
              :style="{
                outline: ringOutline(crop),
                outlineOffset: '-2px',
                opacity: crop.training_eligible ? 1 : 0.55,
              }"
              :title="cropTitle(crop)"
            >
              <img
                :src="imgUrl(crop)"
                loading="lazy"
                class="h-full w-full object-cover"
                :class="{ 'cursor-pointer': canToggle(crop), 'cursor-default': !canToggle(crop) }"
                :style="{ filter: crop.training_eligible ? 'none' : 'grayscale(1)' }"
                @click="onCropClick(crop)"
              />
              <span
                v-if="!crop.training_eligible"
                class="pointer-events-none absolute inset-x-0 bottom-0 bg-black/60 py-0.5 text-center text-[9px] font-medium text-white"
              >exclu</span>

              <!-- Barre d'actions au survol (recadrer / réassigner) -->
              <div
                class="absolute right-0 top-0 flex gap-0.5 p-0.5 opacity-0 transition-opacity group-hover:opacity-100"
              >
                <button
                  type="button"
                  class="flex h-5 w-5 items-center justify-center rounded"
                  style="background: rgba(14,14,31,.72); color: #fff;"
                  title="Recadrer ce crop"
                  @click.stop="openRecrop(crop)"
                >
                  <Crop class="h-3 w-3" />
                </button>
                <button
                  type="button"
                  class="flex h-5 w-5 items-center justify-center rounded"
                  style="background: rgba(14,14,31,.72); color: #fff;"
                  title="Réassigner à la bonne classe"
                  @click.stop="openReassign(crop)"
                >
                  <ArrowRightLeft class="h-3 w-3" />
                </button>
              </div>
            </div>
          </div>
          <p class="mt-2 text-[11px]" style="color: var(--ink-400);">
            Bordure verte = face obverse confirmée, part au train · pointillés =
            face à confirmer (non détectée, pas un défaut de crop) · ambre =
            mauvaise face (côté commun) · rouge = rejeté / non-2€ · gris = exclu.
            R@1 « — » = pas de benchmark récent. Clic = inclure / exclure ;
            survol = recadrer ou réassigner. Effet au prochain re-bake.
          </p>
        </div>
      </div>
    </div>
    </template>
  </DrawerSection>

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
      class="flex max-h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-lg border"
      style="border-color: var(--surface-3); background: var(--surface);"
    >
      <!-- En-tête : crop courant + recalcul Dino + fermer -->
      <header
        class="flex items-center gap-3 border-b px-5 py-3"
        style="border-color: var(--surface-3);"
      >
        <img
          :src="imgUrl(reassignCrop)"
          class="h-12 w-12 shrink-0 rounded-md object-cover"
          style="outline: 1px solid var(--surface-3); outline-offset: -1px;"
        />
        <div class="min-w-0">
          <h3 class="font-display text-base italic font-semibold" style="color: var(--indigo-700);">
            Réassigner le crop
          </h3>
          <p class="truncate text-xs" style="color: var(--ink-400);">
            Actuellement
            <span class="font-mono" style="color: var(--ink-200);">{{ reassignCrop.eurio_id ?? '∅' }}</span>
            — clique la bonne pièce (suggestion Dino ou recherche).
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

      <!-- Corps scrollable : suggestions Dino puis sélecteur libre -->
      <div class="relative min-h-0 flex-1 overflow-y-auto px-5 py-4">
        <p
          v-if="reassignError"
          class="mb-3 rounded-md border px-3 py-2 text-xs"
          style="border-color: var(--danger); color: var(--danger);"
        >
          {{ reassignError }}
        </p>

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
