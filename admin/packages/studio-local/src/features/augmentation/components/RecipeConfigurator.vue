<script setup lang="ts">
import LayerSection from './LayerSection.vue'
import PreviewGrid from './PreviewGrid.vue'
import SaveRecipeModal from './SaveRecipeModal.vue'
import { useRecipeEditor } from '../composables/useRecipeEditor'
import { Loader2, RefreshCw, Save, WifiOff } from 'lucide-vue-next'
import { computed, onMounted, ref, toRef } from 'vue'

// ─── Props / emits ────────────────────────────────────────────────────────

const props = defineProps<{
  eurioId: string | null
  // If provided, the matching recipe will be selected on load.
  initialRecipeId?: string | null
}>()

const emit = defineEmits<{
  'recipe-saved': [recipeId: string, recipeName: string]
}>()

// ─── Editor ───────────────────────────────────────────────────────────────

const eurioIdRef = toRef(props, 'eurioId')
const editor = useRecipeEditor(eurioIdRef)
const {
  apiStatus,
  refreshApiStatus,
  schema,
  customRecipes,
  loadingSchema,
  schemaError,
  loadCatalog,
  slot,
  fixSeed,
  sharedSeed,
  previewCount,
  slotPresetValue,
  applyPresetString,
  loadRecipeById,
  regenerate,
  saveError,
  saveLoading,
  saveRecipe,
  layerForType,
  paramDirtyChecker,
} = editor

// ─── Save modal ───────────────────────────────────────────────────────────

const saveModalOpen = ref(false)

async function onSave(payload: { name: string, zone: string | null }) {
  try {
    const created = await saveRecipe(payload)
    saveModalOpen.value = false
    emit('recipe-saved', created.id, created.name)
  } catch {
    // saveError is already set by saveRecipe
  }
}

// ─── Lifecycle ────────────────────────────────────────────────────────────

onMounted(async () => {
  await refreshApiStatus({ showProbe: true })
  if (apiStatus.value === 'online') {
    await loadCatalog()
    if (props.initialRecipeId) loadRecipeById(props.initialRecipeId)
    if (props.eurioId && slot.loaded) void regenerate()
  }
})

// ─── Helpers ──────────────────────────────────────────────────────────────

const currentPresetValue = computed(() => slotPresetValue())
</script>

<template>
  <!-- Offline -->
  <div
    v-if="apiStatus === 'offline'"
    class="flex items-center gap-3 rounded-md border px-4 py-3 text-sm"
    style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 4%, var(--surface)); color: var(--ink);"
  >
    <WifiOff class="h-4 w-4 shrink-0" style="color: var(--danger);" />
    <span>ML API hors-ligne.</span>
    <button
      class="ml-auto flex items-center gap-1 rounded px-2 py-1 text-xs font-medium"
      style="background: var(--ink); color: var(--surface);"
      @click="refreshApiStatus({ showProbe: true })"
    >
      <RefreshCw class="h-3 w-3" /> Réessayer
    </button>
  </div>

  <!-- Loading -->
  <div
    v-else-if="apiStatus === 'checking' || loadingSchema"
    class="flex items-center gap-2 text-xs"
    style="color: var(--ink-400);"
  >
    <Loader2 class="h-3.5 w-3.5 animate-spin" /> Chargement recettes…
  </div>

  <!-- Error -->
  <p v-else-if="schemaError" class="text-xs" style="color: var(--danger);">{{ schemaError }}</p>

  <!-- No coin selected -->
  <p
    v-else-if="!eurioId"
    class="text-xs"
    style="color: var(--ink-400);"
  >
    Sélectionne une pièce ci-dessus pour prévisualiser.
  </p>

  <!-- Editor -->
  <template v-else-if="schema">
    <!-- Top bar: preset + seed controls -->
    <div class="flex flex-wrap items-center gap-3 mb-3">
      <div class="flex items-center gap-2 min-w-0 flex-1">
        <label class="text-[10px] font-medium uppercase shrink-0" style="color: var(--ink-400);">
          Recette
        </label>
        <select
          :value="currentPresetValue"
          class="flex-1 rounded border px-2 py-1 text-xs"
          style="background: var(--surface-1); border-color: var(--surface-3); color: var(--ink);"
          @change="(e) => applyPresetString((e.target as HTMLSelectElement).value)"
        >
          <option value="" disabled>— choisir —</option>
          <optgroup label="Zones">
            <option v-for="z in ['green', 'orange', 'red']" :key="z" :value="`zone:${z}`">
              Zone {{ z }}
            </option>
          </optgroup>
          <optgroup v-if="customRecipes.length" label="Recettes sauvegardées">
            <option v-for="r in customRecipes" :key="r.id" :value="`custom:${r.id}`">
              {{ r.name }}{{ r.zone ? ` · ${r.zone}` : '' }}
            </option>
          </optgroup>
        </select>
        <span
          v-if="slot.state.dirty"
          class="shrink-0 rounded px-1.5 py-0.5 text-[9px] font-mono uppercase"
          style="background: var(--indigo-700); color: white;"
        >modifié</span>
      </div>

      <div class="flex items-center gap-2 shrink-0">
        <label class="flex items-center gap-1 text-[10px]" style="color: var(--ink-500);">
          <input v-model="fixSeed" type="checkbox" class="accent-indigo-700" />
          seed
        </label>
        <input
          v-if="fixSeed"
          v-model.number="sharedSeed"
          type="number"
          class="w-14 rounded border px-1.5 py-0.5 font-mono text-[10px]"
          style="background: var(--surface-1); border-color: var(--surface-3); color: var(--ink);"
        />
        <input
          v-model.number="previewCount"
          type="number" min="1" max="16"
          class="w-12 rounded border px-1.5 py-0.5 font-mono text-[10px]"
          style="background: var(--surface-1); border-color: var(--surface-3); color: var(--ink);"
          title="Variantes à afficher"
        />
        <button
          class="flex items-center gap-1 rounded px-2.5 py-1 text-xs font-medium"
          style="background: var(--indigo-700); color: white;"
          :disabled="slot.loading"
          @click="regenerate"
        >
          <Loader2 v-if="slot.loading" class="h-3 w-3 animate-spin" />
          <RefreshCw v-else class="h-3 w-3" />
          Aperçu
        </button>
      </div>
    </div>

    <!-- Main: sliders left, preview right -->
    <div class="grid grid-cols-[280px_1fr] gap-4">
      <!-- Sliders -->
      <div class="flex flex-col gap-2 max-h-[50vh] overflow-y-auto pr-1">
        <template v-for="layerSchema in schema.layers" :key="layerSchema.type">
          <LayerSection
            v-if="layerForType(layerSchema.type)"
            :schema="layerSchema"
            :layer="layerForType(layerSchema.type)!.layer"
            :layer-index="layerForType(layerSchema.type)!.index"
            :is-param-dirty="paramDirtyChecker(layerForType(layerSchema.type)!.index)"
            @update="(name, value) => slot.state.updateParam(layerForType(layerSchema.type)!.index, name, value)"
          />
        </template>
      </div>

      <!-- Preview -->
      <div class="flex flex-col gap-2">
        <PreviewGrid
          :images="slot.images"
          :count="previewCount"
          :loading="slot.loading"
          :error="slot.error"
        />
        <p class="font-mono text-[10px]" style="color: var(--ink-400);">
          <template v-if="slot.durationMs">{{ slot.durationMs }} ms · </template>
          <span style="color: var(--ink-300);">aperçu illustratif — seed {{ fixSeed ? sharedSeed : '?' }} — le bake utilise le seed de l'itération</span>
        </p>
      </div>
    </div>

    <!-- Footer: save -->
    <div class="mt-3 flex items-center justify-between border-t pt-3" style="border-color: var(--surface-3);">
      <p v-if="saveError" class="text-xs" style="color: var(--danger);">{{ saveError }}</p>
      <div class="ml-auto">
        <button
          class="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium"
          style="background: var(--indigo-700); color: white;"
          :disabled="saveLoading"
          @click="saveModalOpen = true"
        >
          <Loader2 v-if="saveLoading" class="h-3 w-3 animate-spin" />
          <Save v-else class="h-3 w-3" />
          Sauvegarder comme recette…
        </button>
      </div>
    </div>
  </template>

  <SaveRecipeModal
    :open="saveModalOpen"
    :initial-zone="null"
    :based-on-name="slot.state.baselineName"
    @close="saveModalOpen = false"
    @save="onSave"
  />
</template>
