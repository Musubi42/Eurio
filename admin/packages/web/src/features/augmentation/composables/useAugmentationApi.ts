// Fetch wrappers for the /augmentation/* subsystem served by the local ML API.
//
// Same host as the training composable (http://localhost:8042). Thin layer —
// all error handling + retry happens at the caller site, since the ergonomics
// depend on the action (preview vs save vs load).

import { ML_API } from '@/features/training/composables/useTrainingApi'
import type {
  AugmentationSchemaResponse,
  OverlaysResponse,
  PreviewResponse,
  Recipe,
  RecipeRow,
} from '../types'

export { ML_API }

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${ML_API}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!resp.ok) {
    let body = ''
    try {
      body = await resp.text()
    } catch {
      // ignore
    }
    throw new Error(`${resp.status} ${resp.statusText}: ${body}`)
  }
  return resp.json() as Promise<T>
}

export async function fetchAugmentationSchema(): Promise<AugmentationSchemaResponse> {
  return json<AugmentationSchemaResponse>('/augmentation/schema')
}

export async function fetchOverlays(): Promise<OverlaysResponse> {
  return json<OverlaysResponse>('/augmentation/overlays')
}

export interface PreviewRequest {
  recipe: Recipe
  eurio_id?: string
  design_group_id?: string
  count?: number
  seed?: number | null
}

export async function postPreview(req: PreviewRequest): Promise<PreviewResponse> {
  return json<PreviewResponse>('/augmentation/preview', {
    method: 'POST',
    body: JSON.stringify(req),
  })
}

export async function fetchRecipes(zone?: string | null): Promise<RecipeRow[]> {
  const qs = zone ? `?zone=${encodeURIComponent(zone)}` : ''
  return json<RecipeRow[]>(`/augmentation/recipes${qs}`)
}

export async function fetchRecipe(idOrName: string): Promise<RecipeRow> {
  return json<RecipeRow>(
    `/augmentation/recipes/${encodeURIComponent(idOrName)}`,
  )
}

export interface CreateRecipePayload {
  name: string
  zone?: string | null
  config: Recipe
  based_on_recipe_id?: string | null
}

export async function createRecipe(payload: CreateRecipePayload): Promise<RecipeRow> {
  return json<RecipeRow>('/augmentation/recipes', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateRecipe(
  id: string,
  patch: Partial<Pick<CreateRecipePayload, 'name' | 'zone' | 'config'>>,
): Promise<RecipeRow> {
  return json<RecipeRow>(`/augmentation/recipes/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify(patch),
  })
}

export async function deleteRecipe(id: string): Promise<void> {
  await json<{ deleted: boolean }>(
    `/augmentation/recipes/${encodeURIComponent(id)}`,
    { method: 'DELETE' },
  )
}

// Handoff to training — passes aug_recipe_id per item. Backend resolves
// id-or-name and persists to training_staging.aug_recipe_id (PRD Bloc 1).
export interface StageAugItem {
  class_id: string
  class_kind: 'eurio_id' | 'design_group_id'
  aug_recipe_id?: string | null
}

export async function stageForTraining(
  items: StageAugItem[],
): Promise<void> {
  await json('/training/stage', {
    method: 'POST',
    body: JSON.stringify({ items }),
  })
}
