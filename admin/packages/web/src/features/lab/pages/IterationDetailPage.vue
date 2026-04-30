<script setup lang="ts">
import AugmentationsGallery from '@/features/lab/components/AugmentationsGallery.vue'
import AugVsRealSection from '@/features/lab/components/AugVsRealSection.vue'
import BuildTestAppSection from '@/features/lab/components/BuildTestAppSection.vue'
import LiveTestsSection from '@/features/lab/components/LiveTestsSection.vue'
import InputDiffChip from '@/features/lab/components/InputDiffChip.vue'
import PerConditionTable from '@/features/lab/components/PerConditionTable.vue'
import VerdictBadge from '@/features/lab/components/VerdictBadge.vue'
import { fetchRecipes } from '@/features/augmentation/composables/useAugmentationApi'
import type { RecipeRow } from '@/features/augmentation/types'
import {
  deleteIteration,
  fetchBenchmarkRunDetail,
  fetchIteration,
  fetchIterationAugmentations,
  updateIteration,
} from '@/features/lab/composables/useLabApi'
import {
  useLaunchTrainingMutation,
  useRegenerateAugmentationsMutation,
  useRunnerStatusQuery,
  useStopIterationMutation,
} from '@/features/lab/composables/useLabQueries'
import type {
  BenchmarkRunDetail,
  IterationAugmentations,
  IterationDetail,
  Verdict,
} from '@/features/lab/types'
import { ArrowLeft, ExternalLink, Loader2, Play, Save, Square, Trash2, Wand2 } from 'lucide-vue-next'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const cohortId = computed(() => String(route.params.cohortId))
const iterationId = computed(() => String(route.params.iterationId))

const iteration = ref<IterationDetail | null>(null)
const benchmark = ref<BenchmarkRunDetail | null>(null)
const augmentations = ref<IterationAugmentations | null>(null)
const recipes = ref<RecipeRow[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

const notesDraft = ref<string>('')
const verdictOverrideDraft = ref<Verdict | null>(null)
const savingNotes = ref(false)

// Two-phase pipeline drafts (editable while status === 'pending')
const recipeDraft = ref<string | null>(null)
const variantCountDraft = ref<number>(100)
const savingPipeline = ref(false)
const pipelineError = ref<string | null>(null)

const runnerQuery = useRunnerStatusQuery()
const runnerBusy = computed(() => runnerQuery.data.value?.busy ?? false)

const regenerateMut = useRegenerateAugmentationsMutation(cohortId, iterationId)
const launchMut = useLaunchTrainingMutation(cohortId, iterationId)
const stopMut = useStopIterationMutation(cohortId)

let pollInterval: ReturnType<typeof setInterval> | null = null

onMounted(async () => {
  await Promise.all([reload(), loadRecipes()])
  pollInterval = setInterval(() => {
    if (iteration.value && (iteration.value.status === 'training' || iteration.value.status === 'benchmarking')) {
      reload()
    }
  }, 4000)
})

onUnmounted(() => {
  if (pollInterval) clearInterval(pollInterval)
})

async function loadRecipes() {
  try {
    recipes.value = await fetchRecipes()
  } catch {
    recipes.value = []
  }
}

async function reload() {
  loading.value = true
  error.value = null
  try {
    const it = await fetchIteration(cohortId.value, iterationId.value)
    iteration.value = it
    notesDraft.value = it.notes || ''
    verdictOverrideDraft.value = it.verdict_override
    recipeDraft.value = it.recipe_id
    variantCountDraft.value = it.variant_count
    if (it.benchmark_run_id) {
      benchmark.value = await fetchBenchmarkRunDetail(it.benchmark_run_id).catch(() => null)
    } else {
      benchmark.value = null
    }
    augmentations.value = await fetchIterationAugmentations(
      cohortId.value, iterationId.value,
    ).catch(() => null)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

async function saveNotes() {
  if (!iteration.value) return
  savingNotes.value = true
  try {
    await updateIteration(cohortId.value, iterationId.value, {
      notes: notesDraft.value,
      verdict_override: verdictOverrideDraft.value,
    })
    await reload()
  } catch (e) {
    alert(`Sauvegarde échouée : ${(e as Error).message}`)
  } finally {
    savingNotes.value = false
  }
}

const isPending = computed(() => iteration.value?.status === 'pending')

const pipelineDirty = computed(() => {
  if (!iteration.value) return false
  return recipeDraft.value !== iteration.value.recipe_id
    || variantCountDraft.value !== iteration.value.variant_count
})

const augTotal = computed(() => augmentations.value?.total_samples ?? 0)
const augReady = computed(() => augTotal.value > 0 && !pipelineDirty.value)

async function savePipeline() {
  if (!iteration.value || !pipelineDirty.value) return
  savingPipeline.value = true
  pipelineError.value = null
  try {
    await updateIteration(cohortId.value, iterationId.value, {
      recipe_id: recipeDraft.value,
      variant_count: variantCountDraft.value,
    })
    await reload()
  } catch (e) {
    pipelineError.value = (e as Error).message
  } finally {
    savingPipeline.value = false
  }
}

async function generateAugmentations() {
  if (!iteration.value) return
  pipelineError.value = null
  try {
    if (pipelineDirty.value) await savePipeline()
    await regenerateMut.mutateAsync()
    await reload()
  } catch (e) {
    pipelineError.value = (e as Error).message
  }
}

async function launchTraining() {
  if (!iteration.value) return
  pipelineError.value = null
  try {
    await launchMut.mutateAsync()
    await reload()
  } catch (e) {
    pipelineError.value = (e as Error).message
  }
}

async function handleStop() {
  if (!iteration.value) return
  if (!confirm('Stopper cette itération ? Le training en cours sera interrompu.')) return
  try {
    await stopMut.mutateAsync(iteration.value.id)
    await reload()
  } catch (e) {
    alert(`Stop échoué : ${(e as Error).message}`)
  }
}

async function handleDelete() {
  if (!iteration.value) return
  const ok = confirm(`Supprimer l'itération "${iteration.value.name}" ?`)
  if (!ok) return
  try {
    await deleteIteration(cohortId.value, iterationId.value)
    router.push(`/lab/cohorts/${cohortId.value}`)
  } catch (e) {
    alert(`Suppression échouée : ${(e as Error).message}`)
  }
}

function formatPct(v: number | null | undefined): string {
  if (v == null) return '—'
  return `${(v * 100).toFixed(1)}%`
}

function formatDelta(v: number | undefined): string {
  if (v == null) return '—'
  const sign = v > 0 ? '+' : ''
  return `${sign}${(v * 100).toFixed(2)} pts`
}

function deltaColor(v: number | undefined): string {
  if (v == null) return 'var(--ink-400)'
  if (v > 0.005) return 'var(--success)'
  if (v < -0.005) return 'var(--danger)'
  return 'var(--ink-400)'
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('fr-FR', {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
  })
}

const inProgress = computed(() =>
  iteration.value?.status === 'training' || iteration.value?.status === 'benchmarking',
)

const deltaR1 = computed(() => iteration.value?.delta_vs_parent?.r_at_1)
const perZoneDelta = computed(() => iteration.value?.delta_vs_parent?.per_zone ?? {})
const perCoinDelta = computed(() => iteration.value?.delta_vs_parent?.per_coin ?? {})

watch(iteration, (it) => {
  if (it) {
    notesDraft.value = it.notes || ''
    verdictOverrideDraft.value = it.verdict_override
  }
})
</script>

<template>
  <div class="p-8">
    <button
      class="mb-4 flex items-center gap-1 text-sm"
      style="color: var(--ink-500);"
      @click="router.push(`/lab/cohorts/${cohortId}`)"
    >
      <ArrowLeft class="h-3.5 w-3.5" />
      Retour au cohort
    </button>

    <div v-if="loading && !iteration" class="flex items-center gap-3 text-sm" style="color: var(--ink-500);">
      <Loader2 class="h-4 w-4 animate-spin" />
      Chargement…
    </div>
    <div
      v-else-if="error"
      class="rounded-md border px-4 py-3 text-sm"
      style="border-color: var(--danger); color: var(--ink);"
    >
      {{ error }}
    </div>

    <template v-else-if="iteration">
      <!-- Header -->
      <header class="mb-8">
        <div class="flex items-start justify-between gap-6">
          <div class="min-w-0 flex-1">
            <p
              class="mb-1 text-[10px] font-medium uppercase"
              style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
            >
              Itération · {{ iteration.id }}
            </p>
            <div class="flex items-center gap-3">
              <h1
                class="font-display text-3xl italic font-semibold leading-tight"
                style="color: var(--indigo-700);"
              >
                {{ iteration.name }}
              </h1>
              <VerdictBadge
                :verdict="iteration.verdict"
                :override="iteration.verdict_override"
              />
            </div>
            <p
              v-if="iteration.hypothesis"
              class="mt-2 max-w-2xl text-sm italic"
              style="color: var(--ink-500);"
            >
              « {{ iteration.hypothesis }} »
            </p>
            <div class="mt-3 flex flex-wrap gap-4 text-xs" style="color: var(--ink-500);">
              <span>Démarré : {{ formatDate(iteration.started_at) }}</span>
              <span>Fini : {{ formatDate(iteration.finished_at) }}</span>
              <span v-if="iteration.parent_iteration_id">
                Parent :
                <a
                  class="font-mono underline"
                  style="color: var(--indigo-700);"
                  :href="`/lab/cohorts/${cohortId}/iterations/${iteration.parent_iteration_id}`"
                >{{ iteration.parent_iteration_id }}</a>
              </span>
            </div>
          </div>

          <div class="flex flex-shrink-0 items-start gap-2">
            <button
              v-if="inProgress"
              class="flex items-center gap-1.5 rounded-md border px-3 py-2 text-sm font-medium"
              :style="{
                borderColor: 'var(--danger)',
                color: stopMut.isPending.value ? 'var(--ink-400)' : 'var(--danger)',
                cursor: stopMut.isPending.value ? 'wait' : 'pointer',
              }"
              :disabled="stopMut.isPending.value"
              title="Stopper l'itération en cours"
              @click="handleStop"
            >
              <Loader2 v-if="stopMut.isPending.value" class="h-3.5 w-3.5 animate-spin" />
              <Square v-else class="h-3.5 w-3.5" />
              Stopper
            </button>
            <button
              v-if="!inProgress"
              class="rounded-md border p-2"
              style="border-color: var(--surface-3); color: var(--ink-400);"
              title="Supprimer"
              @click="handleDelete"
            >
              <Trash2 class="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
        <div class="mt-6 h-px w-16" style="background: var(--gold);" />
      </header>

      <!-- In-progress banner -->
      <div
        v-if="inProgress"
        class="mb-8 flex items-center gap-3 rounded-md border px-4 py-3 text-sm"
        style="border-color: var(--warning); background: color-mix(in srgb, var(--warning) 6%, var(--surface)); color: var(--ink);"
      >
        <Loader2 class="h-4 w-4 animate-spin" style="color: var(--warning);" />
        <span>
          {{ iteration.status === 'training' ? 'Training en cours' : 'Benchmark en cours' }}…
          La page se rafraîchit automatiquement.
        </span>
      </div>

      <!-- Failed banner -->
      <div
        v-if="iteration.status === 'failed'"
        class="mb-8 rounded-md border px-4 py-3 text-sm"
        style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 6%, var(--surface)); color: var(--ink);"
      >
        <p class="font-medium" style="color: var(--danger);">Itération en échec</p>
        <p class="mt-1 font-mono text-xs">{{ iteration.error || 'aucun détail' }}</p>
      </div>

      <!-- §0 Two-phase pipeline (status=pending only) -->
      <section
        v-if="isPending"
        class="mb-10 rounded-lg border p-5"
        style="border-color: var(--indigo-700); background: color-mix(in srgb, var(--indigo-700) 4%, var(--surface));"
      >
        <p
          class="mb-4 text-[10px] font-medium uppercase"
          style="color: var(--indigo-700); letter-spacing: var(--tracking-eyebrow);"
        >
          §0 Pipeline · 1) Recette → 2) Bake augmentations → 3) Lancer training
        </p>

        <div class="grid grid-cols-2 gap-4">
          <label class="block">
            <span class="mb-1 block text-[10px] font-medium uppercase" style="color: var(--ink-500);">
              Recette d'augmentation
            </span>
            <div class="flex items-center gap-2">
              <select
                v-model="recipeDraft"
                class="flex-1 rounded-md border px-3 py-2 text-sm"
                style="border-color: var(--surface-3);"
              >
                <option :value="null">— aucune —</option>
                <option v-for="r in recipes" :key="r.id" :value="r.id">
                  {{ r.name }}{{ r.zone ? ` (${r.zone})` : '' }}
                </option>
              </select>
              <a
                href="/augmentation"
                target="_blank"
                class="inline-flex items-center gap-1 rounded-md border px-2 py-2 text-xs"
                style="border-color: var(--surface-3); color: var(--indigo-700);"
                title="Éditer dans Studio"
              >
                <ExternalLink class="h-3 w-3" />
              </a>
            </div>
          </label>

          <div>
            <p class="mb-1 text-[10px] font-medium uppercase" style="color: var(--ink-500);">
              Variant count (images / classe)
            </p>
            <div class="flex items-center gap-4">
              <input
                v-model.number="variantCountDraft"
                type="range" min="50" max="500" step="10"
                class="flex-1"
              />
              <span class="w-12 text-right font-mono tabular-nums" style="color: var(--indigo-700);">
                {{ variantCountDraft }}
              </span>
            </div>
          </div>
        </div>

        <div class="mt-4 flex flex-wrap items-center justify-between gap-3 border-t pt-4" style="border-color: var(--surface-3);">
          <p class="text-xs" style="color: var(--ink-500);">
            <template v-if="pipelineDirty">
              <span style="color: var(--warning);">Config modifiée</span> — sauver effacera les augmentations bakées.
            </template>
            <template v-else-if="augTotal > 0">
              <span style="color: var(--success);">{{ augTotal }} augmentations bakées</span>
              ({{ augmentations?.per_coin.length ?? 0 }} pièces × {{ iteration.variant_count }})
            </template>
            <template v-else>
              Aucune augmentation bakée — clique « Générer ».
            </template>
          </p>

          <div class="flex items-center gap-2">
            <button
              v-if="pipelineDirty"
              class="flex items-center gap-1.5 rounded-md border px-3 py-2 text-xs font-medium"
              :style="{
                borderColor: 'var(--surface-3)',
                color: savingPipeline ? 'var(--ink-400)' : 'var(--ink)',
                cursor: savingPipeline ? 'wait' : 'pointer',
              }"
              :disabled="savingPipeline"
              @click="savePipeline"
            >
              <Loader2 v-if="savingPipeline" class="h-3 w-3 animate-spin" />
              <Save v-else class="h-3 w-3" />
              Sauver config
            </button>
            <button
              class="flex items-center gap-1.5 rounded-md px-3 py-2 text-xs font-medium"
              :style="{
                background: regenerateMut.isPending.value ? 'var(--surface-2)' : 'var(--gold)',
                color: regenerateMut.isPending.value ? 'var(--ink-400)' : 'var(--ink)',
                cursor: regenerateMut.isPending.value ? 'wait' : 'pointer',
              }"
              :disabled="regenerateMut.isPending.value"
              @click="generateAugmentations"
            >
              <Loader2 v-if="regenerateMut.isPending.value" class="h-3 w-3 animate-spin" />
              <Wand2 v-else class="h-3 w-3" />
              {{ augTotal > 0 ? 'Régénérer' : 'Générer' }}
            </button>
            <button
              class="flex items-center gap-1.5 rounded-md px-4 py-2 text-sm font-medium"
              :style="{
                background: (augReady && !runnerBusy && !launchMut.isPending.value) ? 'var(--indigo-700)' : 'var(--surface-2)',
                color: (augReady && !runnerBusy && !launchMut.isPending.value) ? 'white' : 'var(--ink-400)',
                cursor: (augReady && !runnerBusy && !launchMut.isPending.value) ? 'pointer' : 'not-allowed',
                boxShadow: (augReady && !runnerBusy && !launchMut.isPending.value) ? 'var(--shadow-sm)' : 'none',
              }"
              :disabled="!augReady || runnerBusy || launchMut.isPending.value"
              :title="
                runnerBusy ? 'Une itération tourne déjà' :
                pipelineDirty ? 'Sauvegarde la config et regénère d\'abord' :
                augTotal === 0 ? 'Génère les augmentations d\'abord' :
                'Lancer training + benchmark'
              "
              @click="launchTraining"
            >
              <Loader2 v-if="launchMut.isPending.value" class="h-3.5 w-3.5 animate-spin" />
              <Play v-else class="h-3.5 w-3.5" />
              Lancer training
            </button>
          </div>
        </div>

        <div
          v-if="pipelineError"
          class="mt-3 rounded-md border px-3 py-2 text-xs"
          style="border-color: var(--danger); color: var(--ink);"
        >
          {{ pipelineError }}
        </div>
      </section>

      <!-- Metrics + delta grid -->
      <section class="mb-10 grid grid-cols-2 gap-4 md:grid-cols-4">
        <article
          v-for="{ label, value, delta } in [
            { label: 'R@1', value: formatPct(iteration.benchmark_summary?.r_at_1 ?? null), delta: deltaR1 },
            { label: 'R@3', value: formatPct(iteration.benchmark_summary?.r_at_3 ?? null), delta: iteration.delta_vs_parent?.r_at_3 },
            { label: 'R@5', value: formatPct(iteration.benchmark_summary?.r_at_5 ?? null), delta: iteration.delta_vs_parent?.r_at_5 },
            { label: 'Spread moyen', value: iteration.benchmark_summary?.mean_spread != null ? iteration.benchmark_summary.mean_spread.toFixed(3) : '—', delta: undefined },
          ]"
          :key="label"
          class="rounded-lg border p-4"
          style="border-color: var(--surface-3); background: var(--surface); box-shadow: var(--shadow-sm);"
        >
          <p class="text-[10px] font-medium uppercase" style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
            {{ label }}
          </p>
          <p class="mt-1 font-display text-3xl font-semibold tabular-nums leading-none" style="color: var(--indigo-700);">
            {{ value }}
          </p>
          <p
            v-if="delta !== undefined"
            class="mt-1 font-mono text-xs tabular-nums"
            :style="{ color: deltaColor(delta) }"
          >
            {{ formatDelta(delta) }} vs parent
          </p>
        </article>
      </section>

      <div class="grid grid-cols-1 gap-8 lg:grid-cols-[1fr_360px]">
        <div class="space-y-10">
          <!-- Inputs card -->
          <section>
            <p
              class="mb-3 text-[10px] font-medium uppercase"
              style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
            >
              Inputs
            </p>
            <div
              class="rounded-lg border p-5"
              style="border-color: var(--surface-3); background: var(--surface);"
            >
              <dl class="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <dt class="text-[10px] uppercase" style="color: var(--ink-500);">Recette</dt>
                  <dd class="mt-1 font-mono" style="color: var(--ink);">
                    <a
                      v-if="iteration.recipe_id"
                      :href="`/augmentation?eurio_ids=${''}`"
                      target="_blank"
                      class="inline-flex items-center gap-1"
                      style="color: var(--indigo-700);"
                    >
                      {{ iteration.recipe_id }}
                      <ExternalLink class="h-3 w-3" />
                    </a>
                    <span v-else style="color: var(--ink-400);">aucune</span>
                  </dd>
                </div>
                <div>
                  <dt class="text-[10px] uppercase" style="color: var(--ink-500);">Variants / classe</dt>
                  <dd class="mt-1 font-mono" style="color: var(--ink);">{{ iteration.variant_count }}</dd>
                </div>
                <div>
                  <dt class="text-[10px] uppercase" style="color: var(--ink-500);">Training config</dt>
                  <dd class="mt-1 font-mono text-xs" style="color: var(--ink);">
                    {{ JSON.stringify(iteration.training_config) }}
                  </dd>
                </div>
                <div>
                  <dt class="text-[10px] uppercase" style="color: var(--ink-500);">Training run</dt>
                  <dd class="mt-1 font-mono" style="color: var(--ink);">
                    <a
                      v-if="iteration.training_run_id"
                      :href="`/training`"
                      class="inline-flex items-center gap-1"
                      style="color: var(--indigo-700);"
                    >
                      {{ iteration.training_summary?.version ? `v${iteration.training_summary.version}` : iteration.training_run_id }}
                      <ExternalLink class="h-3 w-3" />
                    </a>
                    <span v-else style="color: var(--ink-400);">pas encore</span>
                  </dd>
                </div>
              </dl>
              <div class="mt-4 border-t pt-4" style="border-color: var(--surface-3);">
                <p class="mb-2 text-[10px] uppercase" style="color: var(--ink-500);">
                  Δ inputs vs parent
                </p>
                <InputDiffChip :diff="iteration.diff_from_parent" />
              </div>
            </div>
          </section>

          <!-- Per zone delta -->
          <section v-if="Object.keys(perZoneDelta).length > 0">
            <p
              class="mb-3 text-[10px] font-medium uppercase"
              style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
            >
              Delta par zone
            </p>
            <div
              class="overflow-hidden rounded-lg border"
              style="border-color: var(--surface-3); background: var(--surface);"
            >
              <table class="w-full text-sm">
                <thead>
                  <tr class="border-b" style="border-color: var(--surface-3); background: var(--surface-1);">
                    <th class="px-4 py-2 text-left text-[10px] uppercase" style="color: var(--ink-500);">Zone</th>
                    <th class="px-4 py-2 text-right text-[10px] uppercase" style="color: var(--ink-500);">ΔR@1</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(delta, zone) in perZoneDelta" :key="zone" class="border-b" style="border-color: var(--surface-3);">
                    <td class="px-4 py-2 font-mono text-xs">{{ zone }}</td>
                    <td
                      class="px-4 py-2 text-right font-mono tabular-nums"
                      :style="{ color: deltaColor(delta) }"
                    >
                      {{ formatDelta(delta) }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <!-- Per coin delta -->
          <section v-if="Object.keys(perCoinDelta).length > 0">
            <p
              class="mb-3 text-[10px] font-medium uppercase"
              style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
            >
              Delta par pièce
            </p>
            <div
              class="overflow-hidden rounded-lg border"
              style="border-color: var(--surface-3); background: var(--surface);"
            >
              <table class="w-full text-sm">
                <thead>
                  <tr class="border-b" style="border-color: var(--surface-3); background: var(--surface-1);">
                    <th class="px-4 py-2 text-left text-[10px] uppercase" style="color: var(--ink-500);">eurio_id</th>
                    <th class="px-4 py-2 text-right text-[10px] uppercase" style="color: var(--ink-500);">ΔR@1</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(delta, eid) in perCoinDelta" :key="eid" class="border-b" style="border-color: var(--surface-3);">
                    <td class="px-4 py-2 font-mono text-xs">{{ eid }}</td>
                    <td
                      class="px-4 py-2 text-right font-mono tabular-nums"
                      :style="{ color: deltaColor(delta) }"
                    >
                      {{ formatDelta(delta) }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <!-- Per condition (axis) metrics -->
          <section v-if="benchmark && Object.keys(benchmark.per_condition ?? {}).length > 0">
            <p
              class="mb-3 text-[10px] font-medium uppercase"
              style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
            >
              Par axe de variabilité (photos réelles)
            </p>
            <PerConditionTable :per-condition="benchmark.per_condition ?? {}" />
          </section>

          <!-- Augmentations snapshot (Sprint 1 / D-004) -->
          <section v-if="iteration">
            <AugmentationsGallery
              :cohort-id="cohortId"
              :iteration-id="iteration.id"
              :status="iteration.status"
              :per-coin-limit="12"
            />
          </section>

          <!-- §4 Aug ↔ réelles (Sprint 2 / D-006) -->
          <AugVsRealSection
            v-if="iteration"
            :cohort-id="cohortId"
            :iteration-id="iteration.id"
          />

          <!-- §5 Test app (Sprint 3) -->
          <BuildTestAppSection
            v-if="iteration"
            :cohort-id="cohortId"
            :iteration-id="iteration.id"
            :status="iteration.status"
          />

          <!-- §5 (suite) Live tests (Sprint 4) -->
          <LiveTestsSection
            v-if="iteration"
            :cohort-id="cohortId"
            :iteration-id="iteration.id"
          />
        </div>

        <!-- Notes + verdict override sidebar -->
        <aside class="space-y-6">
          <div
            class="rounded-lg border p-4"
            style="border-color: var(--surface-3); background: var(--surface);"
          >
            <p class="mb-2 text-[10px] font-medium uppercase" style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
              Notes
            </p>
            <textarea
              v-model="notesDraft"
              rows="6"
              placeholder="Observations, intuitions, prochains tests…"
              class="w-full rounded-md border px-3 py-2 text-sm"
              style="border-color: var(--surface-3);"
            />
            <p class="mt-4 mb-2 text-[10px] font-medium uppercase" style="color: var(--ink-500);">
              Override du verdict (optionnel)
            </p>
            <select
              v-model="verdictOverrideDraft"
              class="w-full rounded-md border px-3 py-2 text-xs"
              style="border-color: var(--surface-3);"
            >
              <option :value="null">— auto —</option>
              <option value="better">better</option>
              <option value="worse">worse</option>
              <option value="mixed">mixed</option>
              <option value="no_change">no_change</option>
              <option value="baseline">baseline</option>
            </select>
            <button
              class="mt-3 flex w-full items-center justify-center gap-1.5 rounded-md px-3 py-2 text-xs font-medium"
              :style="{
                background: savingNotes ? 'var(--surface-2)' : 'var(--indigo-700)',
                color: savingNotes ? 'var(--ink-400)' : 'white',
                cursor: savingNotes ? 'wait' : 'pointer',
              }"
              :disabled="savingNotes"
              @click="saveNotes"
            >
              <Loader2 v-if="savingNotes" class="h-3 w-3 animate-spin" />
              <Save v-else class="h-3 w-3" />
              Sauvegarder
            </button>
          </div>
        </aside>
      </div>
    </template>
  </div>
</template>
