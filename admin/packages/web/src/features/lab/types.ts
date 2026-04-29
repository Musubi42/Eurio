// Shapes exposed by /lab/* endpoints.
//
// Keep in sync with ml/api/lab_routes.py — any change to the payloads there
// must be reflected here. Strictly typed so the Vue side never guesses.

export type Verdict = 'pending' | 'baseline' | 'better' | 'worse' | 'mixed' | 'no_change'

export type IterationStatus = 'pending' | 'training' | 'benchmarking' | 'completed' | 'failed'

export type CohortStatus = 'draft' | 'frozen'

export interface CohortSummary {
  id: string
  name: string
  description: string | null
  zone: 'green' | 'orange' | 'red' | null
  eurio_ids: string[]
  status: CohortStatus
  frozen_at: string | null
  iteration_count: number
  best_r_at_1: number | null
  created_at: string | null
  updated_at: string | null
}

export interface CoinCaptureStatus {
  eurio_id: string
  numista_id: number | null
  has_captures: boolean
  num_files: number
  expected_steps: string[]
  missing_steps: string[]
  last_modified: string | null
}

export interface CohortCaptureManifest {
  cohort_id: string
  total_coins: number
  fully_captured: number
  partial: number
  missing: number
  expected_steps: string[]
  per_coin: CoinCaptureStatus[]
}

export interface CohortCsvResult {
  csv_path: string
  csv_content: string
  rows: number
  skipped_no_numista: string[]
  skipped_complete: number
  device_target_path: string
  push_command: string
  pull_command: string
  sync_endpoint_hint: string
}

export interface CohortSyncResult {
  pull_dir: string
  output_dir: string
  total_files: number
  normalized: number
  failures: string[]
  per_class: Record<string, { normalized: number; total: number }>
  captures_copied: number
  captures_skipped_existing: number
  captures_unmapped_eurio_ids: string[]
  duration_s: number
}

export interface BenchmarkSummary {
  id: string
  status: string
  r_at_1: number | null
  r_at_3: number | null
  r_at_5: number | null
  mean_spread: number | null
  num_photos: number
  num_coins: number
  per_zone: Record<string, { r_at_1: number; r_at_3: number; r_at_5: number; num_photos: number }>
}

export interface TrainingSummary {
  id: string
  version: number
  status: string
  recall_at_1: number | null
  error: string | null
}

export interface IterationDetail {
  id: string
  cohort_id: string
  parent_iteration_id: string | null
  name: string
  hypothesis: string | null
  recipe_id: string | null
  variant_count: number
  training_config: Record<string, unknown>
  status: IterationStatus
  training_run_id: string | null
  benchmark_run_id: string | null
  verdict: Verdict | null
  verdict_override: Verdict | null
  delta_vs_parent: {
    r_at_1?: number
    r_at_3?: number
    r_at_5?: number
    per_zone?: Record<string, number>
    per_coin?: Record<string, number>
  }
  diff_from_parent: Record<string, { before: unknown; after: unknown }>
  notes: string | null
  error: string | null
  created_at: string | null
  started_at: string | null
  finished_at: string | null
  benchmark_summary: BenchmarkSummary | null
  training_summary: TrainingSummary | null
}

export interface TrajectoryPoint {
  iteration_id: string
  name: string
  r_at_1: number | null
  verdict: Verdict | null
  status: IterationStatus
  created_at: string | null
}

export interface SensitivityEntry {
  path: string
  observations: number
  avg_delta_r1: number
  direction: '+' | '-' | '='
}

export interface RunnerStatus {
  busy: boolean
}

export interface CohortCreatePayload {
  name: string
  description?: string
  zone?: 'green' | 'orange' | 'red' | null
  eurio_ids: string[]
}

export interface IterationCreatePayload {
  name: string
  hypothesis?: string
  parent_iteration_id?: string | null
  recipe_id?: string | null
  variant_count?: number
  training_config?: Record<string, unknown>
}
