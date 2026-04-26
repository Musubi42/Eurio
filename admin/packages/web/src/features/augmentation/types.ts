// Shape contracts mirroring ml/augmentations/base.py::LayerSchema /
// ml/augmentations/pipeline.py::validate_recipe. Kept in sync manually —
// the FastAPI backend serves the authoritative bounds via /augmentation/schema
// so UI never duplicates them, only types them.

export type ParamType =
  | 'float'
  | 'int'
  | 'bool'
  | 'string'
  | 'list[float]'
  | 'list[string]'

export interface ParamSchema {
  name: string
  type: ParamType
  default: unknown
  min?: number
  max?: number
  step?: number
  length?: number
  options?: string[]
  description: string
}

export interface LayerSchema {
  type: string
  label: string
  description: string
  params: ParamSchema[]
}

export interface AugmentationSchemaResponse {
  layers: LayerSchema[]
  zones: string[]
  default_recipe: Recipe
  limits: {
    preview_count_max: number
    preview_ttl_seconds: number
  }
}

export interface Layer {
  type: string
  probability?: number
  // All other fields are dynamic per layer — indexed by param name.
  [key: string]: unknown
}

export interface Recipe {
  count?: number
  layers: Layer[]
}

export interface RecipeRow {
  id: string
  name: string
  zone: string | null
  config: Recipe
  based_on_recipe_id: string | null
  created_at: string | null
  updated_at: string | null
}

export interface PreviewImage {
  index: number
  url: string
}

export interface PreviewResponse {
  run_id: string
  images: PreviewImage[]
  duration_ms: number
  seed: number | null
}

export interface OverlaysResponse {
  patina: string[]
  dust: string[]
  scratches: string[]
  fingerprints: string[]
}

export type Zone = 'green' | 'orange' | 'red'
