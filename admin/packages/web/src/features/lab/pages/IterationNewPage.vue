<script setup lang="ts">
import {
  createIteration,
  fetchCohort,
  fetchIterations,
  fetchRunnerStatus,
} from '@/features/lab/composables/useLabApi'
import type { CohortSummary, IterationDetail } from '@/features/lab/types'
import { fetchRecipes } from '@/features/augmentation/composables/useAugmentationApi'
import type { RecipeRow } from '@/features/augmentation/types'
import { ArrowLeft, ExternalLink, Loader2, Play } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const cohortId = computed(() => String(route.params.id))

const cohort = ref<CohortSummary | null>(null)
const iterations = ref<IterationDetail[]>([])
const recipes = ref<RecipeRow[]>([])
const runnerBusy = ref(false)

const name = ref<string>('')
const hypothesis = ref<string>('')
const parentId = ref<string | null>(null)
const recipeId = ref<string | null>(null)
const variantCount = ref<number>(100)
const epochs = ref<number>(40)
const batchSize = ref<number>(256)
const mPerClass = ref<number>(4)

const submitting = ref(false)
const error = ref<string | null>(null)

onMounted(async () => {
  try {
    const [c, its, r, runner] = await Promise.all([
      fetchCohort(cohortId.value),
      fetchIterations(cohortId.value),
      fetchRecipes().catch(() => []),
      fetchRunnerStatus().catch(() => ({ busy: false })),
    ])
    cohort.value = c
    iterations.value = its
    recipes.value = r
    runnerBusy.value = runner.busy

    // Prefill from last iteration
    const last = its.length > 0 ? its[its.length - 1] : null
    if (last) {
      parentId.value = last.id
      variantCount.value = last.variant_count
      recipeId.value = last.recipe_id
      const tc = last.training_config || {}
      if (typeof tc.epochs === 'number') epochs.value = tc.epochs
      if (typeof tc.batch_size === 'number') batchSize.value = tc.batch_size
      if (typeof tc.m_per_class === 'number') mPerClass.value = tc.m_per_class
    }
  } catch (e) {
    error.value = (e as Error).message
  }
})

const parentIteration = computed<IterationDetail | null>(() =>
  iterations.value.find(it => it.id === parentId.value) ?? null,
)

const canSubmit = computed(
  () => name.value.trim().length > 0
    && variantCount.value > 0
    && variantCount.value <= 2000
    && !submitting.value
    && !runnerBusy.value,
)

async function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  error.value = null
  try {
    const iter = await createIteration(cohortId.value, {
      name: name.value.trim(),
      hypothesis: hypothesis.value || undefined,
      parent_iteration_id: parentId.value,
      recipe_id: recipeId.value,
      variant_count: variantCount.value,
      training_config: {
        epochs: epochs.value,
        batch_size: batchSize.value,
        m_per_class: mPerClass.value,
      },
    })
    router.push(`/lab/cohorts/${cohortId.value}/iterations/${iter.id}`)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    submitting.value = false
  }
}

const diffPreview = computed(() => {
  if (!parentIteration.value) return [] as string[]
  const changes: string[] = []
  const p = parentIteration.value
  if (variantCount.value !== p.variant_count) {
    changes.push(`variant_count : ${p.variant_count} → ${variantCount.value}`)
  }
  if (recipeId.value !== p.recipe_id) {
    changes.push(`recipe : ${p.recipe_id ?? '—'} → ${recipeId.value ?? '—'}`)
  }
  const tc = p.training_config || {}
  if (typeof tc.epochs === 'number' && tc.epochs !== epochs.value) {
    changes.push(`epochs : ${tc.epochs} → ${epochs.value}`)
  }
  if (typeof tc.batch_size === 'number' && tc.batch_size !== batchSize.value) {
    changes.push(`batch_size : ${tc.batch_size} → ${batchSize.value}`)
  }
  if (typeof tc.m_per_class === 'number' && tc.m_per_class !== mPerClass.value) {
    changes.push(`m_per_class : ${tc.m_per_class} → ${mPerClass.value}`)
  }
  return changes
})
</script>

<template>
  <div class="max-w-3xl p-8">
    <button
      class="mb-4 flex items-center gap-1 text-sm"
      style="color: var(--ink-500);"
      @click="router.push(`/lab/cohorts/${cohortId}`)"
    >
      <ArrowLeft class="h-3.5 w-3.5" />
      Retour au cohort
    </button>

    <header class="mb-8">
      <p
        class="mb-1 text-[10px] font-medium uppercase"
        style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
      >
        Nouvelle itération · {{ cohort?.name ?? '…' }}
      </p>
      <h1
        class="font-display text-3xl italic font-semibold leading-tight"
        style="color: var(--indigo-700);"
      >
        Formule une hypothèse, teste-la
      </h1>
      <p class="mt-1.5 text-sm" style="color: var(--ink-500);">
        L'orchestrateur stage le cohort, lance le training puis le benchmark,
        calcule le verdict et le delta vs parent. Laisse tourner.
      </p>
      <div class="mt-6 h-px w-16" style="background: var(--gold);" />
    </header>

    <div
      v-if="runnerBusy"
      class="mb-6 rounded-md border px-4 py-3 text-sm"
      style="border-color: var(--warning); background: color-mix(in srgb, var(--warning) 8%, var(--surface)); color: var(--ink);"
    >
      Une itération est déjà en cours — attends qu'elle finisse avant d'en lancer
      une nouvelle.
    </div>

    <form class="space-y-6" @submit.prevent="submit">
      <label class="block">
        <span class="mb-1 block text-[10px] font-medium uppercase" style="color: var(--ink-500);">
          Nom de l'itération
        </span>
        <input
          v-model="name"
          type="text"
          placeholder="green-v2 more tilt"
          class="w-full rounded-md border px-3 py-2 text-sm"
          style="border-color: var(--surface-3);"
        />
      </label>

      <label class="block">
        <span class="mb-1 block text-[10px] font-medium uppercase" style="color: var(--ink-500);">
          Hypothèse
        </span>
        <textarea
          v-model="hypothesis"
          rows="2"
          placeholder="Bumper max_tilt_degrees à 25° devrait fermer le gap sur photos tilt>30°"
          class="w-full rounded-md border px-3 py-2 text-sm"
          style="border-color: var(--surface-3);"
        />
      </label>

      <div class="grid grid-cols-2 gap-4">
        <label class="block">
          <span class="mb-1 block text-[10px] font-medium uppercase" style="color: var(--ink-500);">
            Parent
          </span>
          <select
            v-model="parentId"
            class="w-full rounded-md border px-3 py-2 text-sm"
            style="border-color: var(--surface-3);"
          >
            <option :value="null">— aucun (baseline) —</option>
            <option v-for="it in iterations" :key="it.id" :value="it.id">
              {{ it.name }}
            </option>
          </select>
        </label>

        <label class="block">
          <span class="mb-1 block text-[10px] font-medium uppercase" style="color: var(--ink-500);">
            Recette d'augmentation
          </span>
          <div class="flex items-center gap-2">
            <select
              v-model="recipeId"
              class="flex-1 rounded-md border px-3 py-2 text-sm"
              style="border-color: var(--surface-3);"
            >
              <option :value="null">— aucune —</option>
              <option v-for="r in recipes" :key="r.id" :value="r.id">
                {{ r.name }}{{ r.zone ? ` (${r.zone})` : '' }}
              </option>
            </select>
            <a
              :href="`/augmentation?eurio_ids=${cohort?.eurio_ids.join(',') ?? ''}`"
              target="_blank"
              class="inline-flex items-center gap-1 rounded-md border px-2 py-2 text-xs"
              style="border-color: var(--surface-3); color: var(--indigo-700);"
              title="Éditer dans Studio (nouvel onglet)"
            >
              <ExternalLink class="h-3 w-3" />
            </a>
          </div>
        </label>
      </div>

      <div>
        <p class="mb-1 text-[10px] font-medium uppercase" style="color: var(--ink-500);">
          Variant count (images augmentées par classe)
        </p>
        <div class="flex items-center gap-4">
          <input
            v-model.number="variantCount"
            type="range" min="50" max="500" step="10"
            class="flex-1"
          />
          <span class="w-12 text-right font-mono tabular-nums" style="color: var(--indigo-700);">
            {{ variantCount }}
          </span>
        </div>
      </div>

      <div class="grid grid-cols-3 gap-4">
        <label class="block">
          <span class="mb-1 block text-[10px] font-medium uppercase" style="color: var(--ink-500);">Epochs</span>
          <input
            v-model.number="epochs"
            type="number" min="1" max="500"
            class="w-full rounded-md border px-3 py-2 text-sm font-mono"
            style="border-color: var(--surface-3);"
          />
        </label>
        <label class="block">
          <span class="mb-1 block text-[10px] font-medium uppercase" style="color: var(--ink-500);">Batch</span>
          <input
            v-model.number="batchSize"
            type="number" min="8" max="2048"
            class="w-full rounded-md border px-3 py-2 text-sm font-mono"
            style="border-color: var(--surface-3);"
          />
        </label>
        <label class="block">
          <span class="mb-1 block text-[10px] font-medium uppercase" style="color: var(--ink-500);">m/class</span>
          <input
            v-model.number="mPerClass"
            type="number" min="1" max="32"
            class="w-full rounded-md border px-3 py-2 text-sm font-mono"
            style="border-color: var(--surface-3);"
          />
        </label>
      </div>

      <!-- Diff vs parent preview -->
      <div
        v-if="parentIteration"
        class="rounded-lg border p-4"
        style="border-color: var(--surface-3); background: var(--surface);"
      >
        <p class="mb-2 text-[10px] font-medium uppercase" style="color: var(--ink-500);">
          Changements vs parent ({{ parentIteration.name }})
        </p>
        <ul v-if="diffPreview.length > 0" class="space-y-1 text-xs font-mono">
          <li v-for="d in diffPreview" :key="d" style="color: var(--indigo-700);">{{ d }}</li>
        </ul>
        <p v-else class="text-xs italic" style="color: var(--ink-400);">
          Identique au parent — tu relanceras un training avec les mêmes inputs. Utile
          pour mesurer la variance aléatoire.
        </p>
      </div>

      <div
        v-if="error"
        class="rounded-md border px-4 py-3 text-sm"
        style="border-color: var(--danger); color: var(--ink);"
      >
        {{ error }}
      </div>

      <div class="flex justify-end gap-2">
        <button
          type="button"
          class="rounded-md border px-4 py-2 text-sm"
          style="border-color: var(--surface-3); color: var(--ink);"
          @click="router.push(`/lab/cohorts/${cohortId}`)"
        >
          Annuler
        </button>
        <button
          type="submit"
          :disabled="!canSubmit"
          class="flex items-center gap-1.5 rounded-md px-4 py-2 text-sm font-medium"
          :style="{
            background: canSubmit ? 'var(--indigo-700)' : 'var(--surface-2)',
            color: canSubmit ? 'white' : 'var(--ink-400)',
            cursor: canSubmit ? 'pointer' : 'not-allowed',
          }"
        >
          <Loader2 v-if="submitting" class="h-3.5 w-3.5 animate-spin" />
          <Play v-else class="h-3.5 w-3.5" />
          Lancer
        </button>
      </div>
    </form>
  </div>
</template>
