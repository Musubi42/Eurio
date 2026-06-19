<script setup lang="ts">
import {
  fetchCohort,
  fetchIterations,
  fetchRunnerStatus,
} from '@/features/lab/composables/useLabApi'
import { useCreateIterationMutation } from '@/features/lab/composables/useLabQueries'
import type { CohortSummary, IterationDetail } from '@/features/lab/types'
import { ArrowLeft, Loader2, Plus } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const cohortId = computed(() => String(route.params.id))

const cohort = ref<CohortSummary | null>(null)
const iterations = ref<IterationDetail[]>([])
const runnerBusy = ref(false)

const name = ref<string>('')
const hypothesis = ref<string>('')
const parentId = ref<string | null>(null)
const epochs = ref<number>(40)
const batchSize = ref<number>(256)
const mPerClass = ref<number>(4)

// Inherited silently from parent — the user picks recipe + variant_count
// on the iteration detail page (two-phase flow: create → pick recipe → bake).
const inheritedRecipeId = ref<string | null>(null)
const inheritedVariantCount = ref<number>(100)

const error = ref<string | null>(null)

const createMut = useCreateIterationMutation(cohortId)
const submitting = computed(() => createMut.isPending.value)

onMounted(async () => {
  try {
    const [c, its, runner] = await Promise.all([
      fetchCohort(cohortId.value),
      fetchIterations(cohortId.value),
      fetchRunnerStatus().catch(() => ({ busy: false })),
    ])
    cohort.value = c
    iterations.value = its
    runnerBusy.value = runner.busy

    const last = its.length > 0 ? its[its.length - 1] : null
    if (last) {
      parentId.value = last.id
      inheritedRecipeId.value = last.recipe_id
      inheritedVariantCount.value = last.variant_count
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
  () => name.value.trim().length > 0 && !submitting.value,
)

async function submit() {
  if (!canSubmit.value) return
  error.value = null
  try {
    const iter = await createMut.mutateAsync({
      name: name.value.trim(),
      hypothesis: hypothesis.value || undefined,
      parent_iteration_id: parentId.value,
      recipe_id: inheritedRecipeId.value,
      variant_count: inheritedVariantCount.value,
      training_config: {
        epochs: epochs.value,
        batch_size: batchSize.value,
        m_per_class: mPerClass.value,
      },
    })
    router.push(`/lab/cohorts/${cohortId.value}/iterations/${iter.id}`)
  } catch (e) {
    error.value = (e as Error).message
  }
}
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
        Crée d'abord l'itération en draft. Tu choisis la recette d'augmentation
        et le variant_count sur la page de l'itération, puis tu baques les
        augmentations avant de lancer le training.
      </p>
      <div class="mt-6 h-px w-16" style="background: var(--gold);" />
    </header>

    <div
      v-if="runnerBusy"
      class="mb-6 rounded-md border px-4 py-3 text-sm"
      style="border-color: var(--warning); background: color-mix(in srgb, var(--warning) 8%, var(--surface)); color: var(--ink);"
    >
      Une itération est déjà en cours d'exécution — tu peux quand même créer une
      itération en draft, le training se lancera quand le runner sera libre.
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
        <p v-if="parentIteration" class="mt-1 text-[11px]" style="color: var(--ink-400);">
          Recette + variant_count hérités de
          <code class="font-mono" style="color: var(--indigo-700);">{{ parentIteration.name }}</code>
          (modifiable ensuite).
        </p>
      </label>

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
          <Plus v-else class="h-3.5 w-3.5" />
          Créer l'itération
        </button>
      </div>
    </form>
  </div>
</template>
