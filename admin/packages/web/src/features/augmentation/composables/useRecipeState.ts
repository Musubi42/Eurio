// Mutable recipe state + dirty tracking. The baseline is whatever was loaded
// (preset or saved recipe) — editing a param diverges `current` from it and
// flips `dirty` true. Resetting to baseline or loading a new one clears dirty.

import { computed, ref } from 'vue'
import type { Layer, LayerSchema, ParamSchema, Recipe } from '../types'

function cloneRecipe(r: Recipe): Recipe {
  return JSON.parse(JSON.stringify(r)) as Recipe
}

export function useRecipeState(initial: Recipe) {
  const current = ref<Recipe>(cloneRecipe(initial))
  const baseline = ref<Recipe>(cloneRecipe(initial))
  const baselineName = ref<string>('default')

  const dirty = computed(
    () => JSON.stringify(current.value) !== JSON.stringify(baseline.value),
  )

  function loadRecipe(recipe: Recipe, name: string = 'custom') {
    current.value = cloneRecipe(recipe)
    baseline.value = cloneRecipe(recipe)
    baselineName.value = name
  }

  function resetToBaseline() {
    current.value = cloneRecipe(baseline.value)
  }

  function updateParam(layerIndex: number, paramName: string, value: unknown) {
    const layer = current.value.layers[layerIndex]
    if (!layer) return
    // Immutable update so computed deps trigger.
    const newLayer = { ...layer, [paramName]: value }
    const newLayers = [...current.value.layers]
    newLayers[layerIndex] = newLayer
    current.value = { ...current.value, layers: newLayers }
  }

  function setCount(n: number) {
    current.value = { ...current.value, count: n }
  }

  // Ensure every layer declared in the schema has a corresponding entry in
  // current.layers, filled with schema defaults if missing. Preserves the
  // order defined by the schema (perspective → relighting → overlays).
  function ensureLayersFromSchema(schemaLayers: LayerSchema[]) {
    const byType = new Map<string, Layer>(
      current.value.layers.map(l => [l.type, l]),
    )
    const merged: Layer[] = schemaLayers.map(sl => {
      const existing = byType.get(sl.type)
      if (existing) return existing
      const base: Layer = { type: sl.type }
      for (const p of sl.params) {
        base[p.name] = p.default as never
      }
      base.probability = 0 // off by default when auto-added
      return base
    })
    current.value = { ...current.value, layers: merged }
  }

  // Returns a list of {layer_index, param_name} for params that diverge from
  // baseline — used by the "— modifié" hairline on each control.
  function isParamDirty(layerIndex: number, paramName: string): boolean {
    const curLayer = current.value.layers[layerIndex]
    const baseLayer = baseline.value.layers.find(l => l?.type === curLayer?.type)
    if (!curLayer || !baseLayer) return false
    return JSON.stringify(curLayer[paramName]) !== JSON.stringify(baseLayer[paramName])
  }

  return {
    current,
    baseline,
    baselineName,
    dirty,
    loadRecipe,
    resetToBaseline,
    updateParam,
    setCount,
    ensureLayersFromSchema,
    isParamDirty,
  }
}

export function defaultValueForParam(p: ParamSchema): unknown {
  return p.default
}
