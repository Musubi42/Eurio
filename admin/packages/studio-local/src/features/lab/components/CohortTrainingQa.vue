<script setup lang="ts">
/**
 * QA des crops d'entraînement par classe — le maillon INSPECT de la boucle
 * d'amélioration (docs/work-in-progress/improvement-loop/03-crop-triage-ux.md).
 *
 * Cockpit de triage, pas une galerie : les classes sont rangées « à inspecter
 * d'abord » (R@1 studio croissant), les crops « suspect d'abord » (face ≠
 * obverse, qualité basse). Exclure un crop (clic) le sort du train en direct
 * (training_eligible=0, réversible) — le prochain bake le drop automatiquement.
 */
import DrawerSection from '@/features/lab/components/DrawerSection.vue'
import { ML_API } from '@/features/training/composables/useTrainingApi'
import {
  useCohortTrainingCropsQuery,
  useSetTrainingEligibleMutation,
} from '@/features/lab/composables/useLabQueries'
import type { DrawerState, TrainingCrop, TrainingCropClass } from '@/features/lab/types'
import { ChevronRight, Loader2 } from 'lucide-vue-next'
import { computed, reactive } from 'vue'

const props = defineProps<{ cohortId: string }>()
const cohortId = computed(() => props.cohortId)

const query = useCohortTrainingCropsQuery(cohortId)
const toggle = useSetTrainingEligibleMutation(cohortId)

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
  if (r < 0.5) return 'var(--danger, #dc2626)'
  if (r < 0.8) return 'var(--warning, #d97706)'
  return 'var(--success, #16a34a)'
}
function r1Label(r: number | null): string {
  return r == null ? '—' : (r * 100).toFixed(0) + '%'
}

function imgUrl(c: TrainingCrop): string {
  return `${ML_API}${c.file_url}`
}

/** Anneau : rouge = rejeté/non-2€, ambre = face non-obverse, sinon neutre. */
function ringColor(c: TrainingCrop): string {
  if (c.resolution_status === 'rejected' || c.denom === 'not_2eur')
    return 'var(--danger, #dc2626)'
  if (c.face !== 'obverse') return 'var(--warning, #d97706)'
  return 'var(--surface-3)'
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
</script>

<template>
  <DrawerSection
    number="C5"
    title="QA crops d'entraînement"
    :state="state"
    :summary="summary"
  >
    <template #body>
    <p class="mb-3 text-xs" style="color: var(--ink-400);">
      Repérer et exclure les déchets, classe par classe — rangé par R@1 à
      inspecter d'abord. Clic sur une vignette = inclure / exclure du train
      (réversible, effet au prochain re-bake).
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
      style="border-color: var(--surface-3); color: var(--danger, #dc2626);"
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
            <span v-if="c.n_unknown_face > 0" style="color: var(--warning, #d97706);">
              {{ c.n_unknown_face }} face ?
            </span>
            <span v-if="c.n_rejected > 0">{{ c.n_rejected }} rej</span>
            <span
              class="inline-flex min-w-[2.75rem] justify-center rounded-md px-1.5 py-0.5 font-semibold text-white"
              :style="{ background: r1Color(c.r_at_1) }"
              title="R@1 studio (dernière itération)"
            >R@1 {{ r1Label(c.r_at_1) }}</span>
          </span>
        </button>

        <!-- Grille de crops -->
        <div v-if="isOpen(c)" class="border-t px-3 py-3" style="border-color: var(--surface-3);">
          <p v-if="!c.crops.length" class="text-xs" style="color: var(--ink-400);">
            Aucun crop. (classe sans données propres — sourcer ou retirer)
          </p>
          <div v-else class="flex flex-wrap gap-1.5">
            <button
              v-for="crop in c.crops"
              :key="crop.asset_id"
              type="button"
              class="relative h-16 w-16 overflow-hidden rounded-md"
              :class="{ 'cursor-default': !canToggle(crop) }"
              :style="{
                outline: `2px solid ${ringColor(crop)}`,
                outlineOffset: '-2px',
                opacity: crop.training_eligible ? 1 : 0.32,
              }"
              :title="cropTitle(crop)"
              @click="onCropClick(crop)"
            >
              <img
                :src="imgUrl(crop)"
                loading="lazy"
                class="h-full w-full object-cover"
                :style="{ filter: crop.training_eligible ? 'none' : 'grayscale(1)' }"
              />
              <span
                v-if="!crop.training_eligible"
                class="absolute inset-x-0 bottom-0 bg-black/60 py-0.5 text-center text-[9px] font-medium text-white"
              >exclu</span>
            </button>
          </div>
          <p class="mt-2 text-[11px]" style="color: var(--ink-400);">
            Anneau ambre = face non-obverse · rouge = rejeté / non-2€. Clic =
            inclure / exclure du train (réversible). Les exclusions prennent effet
            au prochain re-bake.
          </p>
        </div>
      </div>
    </div>
    </template>
  </DrawerSection>
</template>
