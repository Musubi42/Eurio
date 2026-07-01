// Fetch wrappers for the augmentation subsystem — split by weight (Model B) :
//
//  - **Rendu lourd** (schema / overlays / preview) → ML API local `:8042`
//    (`ML_API`), qui a besoin du pipeline cv2. Grisé en hébergé.
//  - **CRUD recettes** (métadonnée pure : nom/zone/JSON) → API CANONIQUE
//    `eurioApi` (VPS = writer unique). Une recette créée ici atterrit dans la DB
//    canonique → récupérable Mac ↔ PC après `ml:db:pull-replica`. Marche dans les
//    deux modes (PAT local / cookie hébergé).

import { ML_API } from '@/features/training/composables/useTrainingApi'
import { eurioApi } from '@/shared/api/eurio-api'
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

// ─── Recettes : CRUD canonique (eurio-api, writer unique) ────────────────────

export async function fetchRecipes(zone?: string | null): Promise<RecipeRow[]> {
  const qs = zone ? `?zone=${encodeURIComponent(zone)}` : ''
  return eurioApi.get<RecipeRow[]>(`/recipes${qs}`)
}

export async function fetchRecipe(idOrName: string): Promise<RecipeRow> {
  return eurioApi.get<RecipeRow>(`/recipes/${encodeURIComponent(idOrName)}`)
}

export interface CreateRecipePayload {
  name: string
  zone?: string | null
  config: Recipe
  based_on_recipe_id?: string | null
}

export async function createRecipe(payload: CreateRecipePayload): Promise<RecipeRow> {
  return eurioApi.post<RecipeRow>('/recipes', payload)
}

export async function updateRecipe(
  id: string,
  patch: Partial<Pick<CreateRecipePayload, 'name' | 'zone' | 'config'>>,
): Promise<RecipeRow> {
  return eurioApi.put<RecipeRow>(`/recipes/${encodeURIComponent(id)}`, patch)
}

export async function deleteRecipe(id: string): Promise<void> {
  await eurioApi.delete<{ deleted: boolean }>(`/recipes/${encodeURIComponent(id)}`)
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
