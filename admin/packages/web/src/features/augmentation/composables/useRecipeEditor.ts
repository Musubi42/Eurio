// Encapsulate schema + recipes catalog + single-slot recipe editing.
//
// Extracted so both AugmentationStudioPage (full studio, multi-coin) and
// IterationDetailPage (inline configurator, single cohort coin) can share
// the same state logic without duplicating 200 lines of script.

import { computed, reactive, ref, watch, type Ref, type UnwrapNestedRefs } from 'vue'
import {
  createRecipe,
  fetchAugmentationSchema,
  fetchRecipes,
  postPreview,
} from './useAugmentationApi'
import { useRecipeState } from './useRecipeState'
import { checkMlApi } from '@/features/training/composables/useTrainingApi'
import type {
  AugmentationSchemaResponse,
  Layer,
  PreviewImage,
  RecipeRow,
} from '../types'

type UnwrappedRecipeState = UnwrapNestedRefs<ReturnType<typeof useRecipeState>>

export interface EditorSlot {
  state: UnwrappedRecipeState
  loaded: boolean
  recipeId: string | null
  images: PreviewImage[]
  runId: string | null
  seed: number
  durationMs: number
  loading: boolean
  error: string | null
}

export function newEditorSlot(): EditorSlot {
  const state = useRecipeState({ layers: [] }) as unknown as UnwrappedRecipeState
  return reactive({
    state,
    loaded: false,
    recipeId: null as string | null,
    images: [] as PreviewImage[],
    runId: null as string | null,
    seed: 42,
    durationMs: 0,
    loading: false,
    error: null as string | null,
  }) as EditorSlot
}

export function useRecipeEditor(eurioId: Ref<string | null>) {
  // ─── API status ───────────────────────────────────────────────────────

  const apiStatus = ref<'checking' | 'online' | 'offline'>('checking')

  async function refreshApiStatus(opts: { showProbe?: boolean } = {}) {
    if (opts.showProbe) apiStatus.value = 'checking'
    const online = await checkMlApi()
    apiStatus.value = online ? 'online' : 'offline'
  }

  // ─── Catalog ──────────────────────────────────────────────────────────

  const schema = ref<AugmentationSchemaResponse | null>(null)
  const customRecipes = ref<RecipeRow[]>([])
  const loadingSchema = ref(true)
  const schemaError = ref<string | null>(null)

  async function loadCatalog() {
    if (apiStatus.value !== 'online') return
    loadingSchema.value = true
    schemaError.value = null
    try {
      const [s, rs] = await Promise.all([fetchAugmentationSchema(), fetchRecipes()])
      schema.value = s
      customRecipes.value = rs
      if (!slot.loaded) {
        slot.state.loadRecipe(s.default_recipe, 'orange')
        slot.state.ensureLayersFromSchema(s.layers)
        slot.loaded = true
      }
    } catch (err) {
      schemaError.value = err instanceof Error ? err.message : 'Failed to load'
    } finally {
      loadingSchema.value = false
    }
  }

  // ─── Slot ─────────────────────────────────────────────────────────────

  const slot = newEditorSlot()

  // ─── Preview controls ─────────────────────────────────────────────────

  const fixSeed = ref(true)
  const sharedSeed = ref(42)
  const previewCount = ref(9)

  // ─── Presets ──────────────────────────────────────────────────────────

  const presetOptions = computed<{ group: 'zone' | 'custom', name: string, label: string }[]>(() => {
    const zones = (['green', 'orange', 'red'] as const).map(z => ({
      group: 'zone' as const,
      name: z,
      label: `Zone ${z}`,
    }))
    const custom = customRecipes.value.map(r => ({
      group: 'custom' as const,
      name: r.id,
      label: `${r.name}${r.zone ? ` · ${r.zone}` : ''}`,
    }))
    return [...zones, ...custom]
  })

  function slotPresetValue(): string {
    if (slot.recipeId) return `custom:${slot.recipeId}`
    const name = slot.state.baselineName
    if (['green', 'orange', 'red'].includes(name)) return `zone:${name}`
    return ''
  }

  function _loadPresetIntoSlot(presetName: string) {
    if (!schema.value) return
    if (presetName === 'orange') {
      slot.state.loadRecipe(schema.value.default_recipe, 'orange')
      slot.state.ensureLayersFromSchema(schema.value.layers)
      slot.recipeId = null
      return
    }
    const exact = customRecipes.value.find(r => r.name === presetName)
    if (exact) {
      slot.state.loadRecipe(exact.config, exact.name)
      slot.state.ensureLayersFromSchema(schema.value.layers)
      slot.recipeId = exact.id
      return
    }
    const byZone = customRecipes.value.find(r => r.zone === presetName)
    if (byZone) {
      slot.state.loadRecipe(byZone.config, byZone.name)
      slot.state.ensureLayersFromSchema(schema.value.layers)
      slot.recipeId = byZone.id
      return
    }
    slot.state.loadRecipe(schema.value.default_recipe, presetName)
    slot.state.ensureLayersFromSchema(schema.value.layers)
    slot.recipeId = null
  }

  function applyPresetString(value: string) {
    const match = presetOptions.value.find(p => `${p.group}:${p.name}` === value)
    if (!match) return
    if (match.group === 'zone') {
      _loadPresetIntoSlot(match.name)
    } else {
      const r = customRecipes.value.find(c => c.id === match.name)
      if (r && schema.value) {
        slot.state.loadRecipe(r.config, r.name)
        slot.state.ensureLayersFromSchema(schema.value.layers)
        slot.recipeId = r.id
      }
    }
  }

  function loadRecipeById(recipeId: string) {
    if (!schema.value) return
    const r = customRecipes.value.find(c => c.id === recipeId)
    if (!r) return
    slot.state.loadRecipe(r.config, r.name)
    slot.state.ensureLayersFromSchema(schema.value.layers)
    slot.recipeId = r.id
  }

  // ─── Regenerate ───────────────────────────────────────────────────────

  async function regenerate() {
    const eid = eurioId.value
    if (!eid) return
    slot.loading = true
    slot.error = null
    try {
      const seed = fixSeed.value ? sharedSeed.value : null
      const res = await postPreview({
        recipe: { ...slot.state.current, count: previewCount.value },
        eurio_id: eid,
        count: previewCount.value,
        seed,
      })
      slot.images = res.images
      slot.runId = res.run_id
      slot.seed = res.seed ?? 0
      slot.durationMs = res.duration_ms
    } catch (err) {
      slot.error = err instanceof Error ? err.message : 'Échec génération'
      slot.images = []
    } finally {
      slot.loading = false
    }
  }

  watch(eurioId, (eid) => {
    if (eid && schema.value && slot.loaded) void regenerate()
  })

  watch(apiStatus, async (status, prev) => {
    if (status === 'online' && prev !== 'online') await loadCatalog()
  })

  // ─── Save ─────────────────────────────────────────────────────────────

  const saveError = ref<string | null>(null)
  const saveLoading = ref(false)

  async function saveRecipe(payload: { name: string, zone: string | null }): Promise<RecipeRow> {
    saveLoading.value = true
    saveError.value = null
    try {
      const created = await createRecipe({
        name: payload.name,
        zone: payload.zone,
        config: slot.state.current,
        based_on_recipe_id: slot.recipeId,
      })
      customRecipes.value = [created, ...customRecipes.value]
      slot.state.loadRecipe(created.config, created.name)
      if (schema.value) slot.state.ensureLayersFromSchema(schema.value.layers)
      slot.recipeId = created.id
      void regenerate()
      return created
    } catch (err) {
      saveError.value = err instanceof Error ? err.message : 'Save failed'
      throw err
    } finally {
      saveLoading.value = false
    }
  }

  // ─── Template helpers ─────────────────────────────────────────────────

  function layerForType(type: string): { layer: Layer, index: number } | null {
    const idx = slot.state.current.layers.findIndex((l: Layer) => l.type === type)
    if (idx < 0) return null
    return { layer: slot.state.current.layers[idx], index: idx }
  }

  function paramDirtyChecker(layerIndex: number) {
    return (paramName: string) => slot.state.isParamDirty(layerIndex, paramName)
  }

  return {
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
    presetOptions,
    slotPresetValue,
    applyPresetString,
    loadRecipeById,
    regenerate,
    saveError,
    saveLoading,
    saveRecipe,
    layerForType,
    paramDirtyChecker,
  }
}
