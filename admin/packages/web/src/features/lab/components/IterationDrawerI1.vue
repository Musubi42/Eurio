<script setup lang="ts">
// Tiroir I1 — Recipe d'augmentation.
// Mutable seulement quand iteration.status === 'pending'. Sinon read-only
// (recipe figée, configurateur masqué).

import DrawerSection from '@/features/lab/components/DrawerSection.vue'
import RecipeConfigurator from '@/features/augmentation/components/RecipeConfigurator.vue'
import { fetchRecipes } from '@/features/augmentation/composables/useAugmentationApi'
import type { RecipeRow } from '@/features/augmentation/types'
import { updateIteration } from '@/features/lab/composables/useLabApi'
import type {
  CohortSummary,
  IterationDetail,
  IterationProgressI1,
} from '@/features/lab/types'
import { useQueryClient } from '@tanstack/vue-query'
import { ChevronDown, ChevronUp, Loader2, Save, Sparkles } from 'lucide-vue-next'
import { computed, onMounted, ref, watch } from 'vue'

const props = defineProps<{
  cohortId: string
  iteration: IterationDetail
  cohort: CohortSummary | null
  progress: IterationProgressI1 | null
}>()

const qc = useQueryClient()

const isPending = computed(() => props.iteration.status === 'pending')
const recipes = ref<RecipeRow[]>([])
const recipeDraft = ref<string | null>(props.iteration.recipe_id)
const variantDraft = ref<number>(props.iteration.variant_count)
const configuratorOpen = ref(false)
const previewEurioId = ref<string | null>(null)
const saving = ref(false)
const error = ref<string | null>(null)

watch(
  () => props.iteration,
  (it) => {
    recipeDraft.value = it.recipe_id
    variantDraft.value = it.variant_count
  },
)

watch(
  () => props.cohort,
  (c) => {
    if (c?.eurio_ids.length && !previewEurioId.value)
      previewEurioId.value = c.eurio_ids[0]
  },
  { immediate: true },
)

onMounted(async () => {
  try {
    recipes.value = await fetchRecipes()
  }
  catch {
    recipes.value = []
  }
})

const dirty = computed(() =>
  recipeDraft.value !== props.iteration.recipe_id
  || variantDraft.value !== props.iteration.variant_count,
)

const summary = computed(() => {
  const p = props.progress
  if (!p || p.state === 'empty')
    return 'Aucune recipe sélectionnée'
  const name = p.recipe_name || p.recipe_id || '—'
  if (isPending.value)
    return `${name} · ${p.variant_count} samples / pièce`
  return `${name} · figée`
})

async function save() {
  if (!dirty.value) return
  saving.value = true
  error.value = null
  try {
    await updateIteration(props.cohortId, props.iteration.id, {
      recipe_id: recipeDraft.value,
      variant_count: variantDraft.value,
    })
    qc.invalidateQueries({ queryKey: ['lab', 'cohort', props.cohortId] })
    qc.invalidateQueries({
      queryKey: ['lab', 'cohort', props.cohortId, 'iterations'],
    })
  }
  catch (e) {
    error.value = (e as Error).message
  }
  finally {
    saving.value = false
  }
}

function onRecipeSaved(recipeId: string) {
  recipeDraft.value = recipeId
  fetchRecipes().then((r) => { recipes.value = r }).catch(() => {})
}
</script>

<template>
  <DrawerSection
    number="I1"
    title="Recipe d'augmentation"
    :state="progress?.state ?? 'empty'"
    :summary="summary"
  >
    <template #body>
      <div v-if="!isPending" class="text-sm" style="color: var(--ink-500);">
        <p>
          Recipe : <span class="font-mono" style="color: var(--ink);">
            {{ progress?.recipe_name || progress?.recipe_id || '—' }}
          </span>
        </p>
        <p class="mt-1">
          Variants / pièce : <span class="font-mono" style="color: var(--ink);">
            {{ progress?.variant_count }}
          </span>
        </p>
        <p class="mt-2 text-xs" style="color: var(--ink-400);">
          Iteration {{ iteration.status }} — recipe figée.
        </p>
      </div>

      <div v-else class="grid grid-cols-2 gap-4">
        <label class="block">
          <span class="mb-1 block text-[10px] font-medium uppercase" style="color: var(--ink-500);">
            Recette
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
            <button
              class="inline-flex items-center gap-1 rounded-md border px-2 py-2 text-xs"
              :style="{
                borderColor: configuratorOpen ? 'var(--indigo-700)' : 'var(--surface-3)',
                color: configuratorOpen ? 'var(--indigo-700)' : 'var(--ink-400)',
              }"
              title="Créer / éditer une recette inline"
              @click="configuratorOpen = !configuratorOpen"
            >
              <Sparkles class="h-3 w-3" />
              <ChevronUp v-if="configuratorOpen" class="h-3 w-3" />
              <ChevronDown v-else class="h-3 w-3" />
            </button>
          </div>
        </label>

        <div>
          <p class="mb-1 text-[10px] font-medium uppercase" style="color: var(--ink-500);">
            Variant count (images / classe)
          </p>
          <div class="flex items-center gap-4">
            <input
              v-model.number="variantDraft"
              type="range" min="50" max="500" step="10"
              class="flex-1"
            />
            <span class="w-12 text-right font-mono tabular-nums" style="color: var(--indigo-700);">
              {{ variantDraft }}
            </span>
          </div>
        </div>
      </div>

      <div
        v-if="isPending && configuratorOpen"
        class="mt-4 rounded-md border p-4"
        style="border-color: var(--surface-3); background: var(--surface);"
      >
        <div class="mb-3 flex items-center justify-between gap-2">
          <p class="text-[10px] font-medium uppercase" style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);">
            Configurateur de recette
          </p>
          <div class="flex items-center gap-2">
            <label class="text-[10px]" style="color: var(--ink-500);">Pièce de preview :</label>
            <select
              v-model="previewEurioId"
              class="rounded border px-2 py-1 text-xs"
              style="background: var(--surface-1); border-color: var(--surface-3); color: var(--ink);"
            >
              <option v-for="eid in cohort?.eurio_ids ?? []" :key="eid" :value="eid">
                {{ eid }}
              </option>
            </select>
          </div>
        </div>
        <RecipeConfigurator
          :eurio-id="previewEurioId"
          :initial-recipe-id="recipeDraft"
          @recipe-saved="onRecipeSaved"
        />
      </div>

      <div v-if="isPending && dirty" class="mt-4 flex items-center justify-end gap-3">
        <p class="text-xs" style="color: var(--warning);">
          Config modifiée — sauver effacera les augmentations bakées.
        </p>
        <button
          class="flex items-center gap-1.5 rounded-md border px-3 py-2 text-xs font-medium"
          :style="{
            borderColor: 'var(--surface-3)',
            color: saving ? 'var(--ink-400)' : 'var(--ink)',
            cursor: saving ? 'wait' : 'pointer',
          }"
          :disabled="saving"
          @click="save"
        >
          <Loader2 v-if="saving" class="h-3 w-3 animate-spin" />
          <Save v-else class="h-3 w-3" />
          Sauver
        </button>
      </div>

      <p v-if="error" class="mt-3 rounded-md border px-3 py-2 text-xs" style="border-color: var(--danger); color: var(--ink);">
        {{ error }}
      </p>
    </template>
  </DrawerSection>
</template>
