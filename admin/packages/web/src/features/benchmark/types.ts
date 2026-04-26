// Shapes for /benchmark/* responses served by the local ML API.
//
// Kept strict: any field the API sends is declared here, so the Studio /
// cockpit pages never guess.

export type BenchmarkStatus = 'running' | 'completed' | 'failed'

export type Zone = 'green' | 'orange' | 'red' | 'unknown'

export interface BenchmarkRunSummary {
  id: string
  model_path: string
  model_name: string
  training_run_id: string | null
  recipe_id: string | null
  zones: string[]
  num_photos: number
  num_coins: number
  num_zones: number
  r_at_1: number | null
  r_at_3: number | null
  r_at_5: number | null
  mean_spread: number | null
  per_zone: Record<string, { r_at_1: number; r_at_3: number; r_at_5: number; num_photos: number }>
  report_path: string
  status: BenchmarkStatus
  error: string | null
  started_at: string | null
  finished_at: string | null
}

export interface BenchmarkPerCoin {
  eurio_id: string
  zone: string | null
  num_photos: number
  r_at_1: number
  r_at_3: number
  r_at_5: number
}

export interface BenchmarkTopConfusion {
  photo_path: string
  ground_truth: string
  zone: string | null
  spread: number
  top_3: { class_id: string; similarity: number }[]
}

export interface BenchmarkRunDetail extends BenchmarkRunSummary {
  eurio_ids: string[]
  per_coin: BenchmarkPerCoin[]
  per_condition: Record<string, Record<string, { r_at_1: number; r_at_3: number; num_photos: number }>>
  confusion: Record<string, Record<string, number>>
  top_confusions: BenchmarkTopConfusion[]
}

export interface BenchmarkLibraryCoin {
  eurio_id: string
  zone: string | null
  num_photos: number
  num_sessions: number
  warnings: string[]
}

export interface BenchmarkLibrary {
  available: boolean
  num_coins: number
  num_photos: number
  by_zone: Record<string, number>
  coins: BenchmarkLibraryCoin[]
}

export interface BenchmarkRunsList {
  items: BenchmarkRunSummary[]
  total: number
}

export interface BenchmarkPhoto {
  filename: string
  path: string
  size_bytes: number
  thumbnail_url: string
}

export interface BenchmarkPhotosResponse {
  eurio_id: string
  zone: string | null
  photos: BenchmarkPhoto[]
}

export interface RunBenchmarkPayload {
  model_path: string
  eurio_ids?: string[]
  zones?: string[]
  recipe_id?: string | null
  run_id?: string
  top_confusions?: number
}
