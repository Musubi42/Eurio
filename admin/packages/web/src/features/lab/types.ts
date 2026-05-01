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
  recipe_name: string | null
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
  augmentations_seed: number | null
  created_at: string | null
  started_at: string | null
  finished_at: string | null
  benchmark_summary: BenchmarkSummary | null
  training_summary: TrainingSummary | null
}

export interface IterationAugmentationCoin {
  eurio_id: string
  numista_id: number | null
  samples: string[]
}

export interface IterationAugmentations {
  iteration_id: string
  augmentations_seed: number | null
  variant_count: number
  total_samples: number
  per_coin: IterationAugmentationCoin[]
}

export interface RegenerateAugmentationsResult {
  iteration_id: string
  regenerated: boolean
  per_coin: Array<{
    eurio_id: string
    numista_id: number | null
    written: number
    skipped_reason: string | null
  }>
}

export interface StopIterationResult {
  iteration_id: string
  outcome: 'graceful' | 'forced' | 'idle'
  marked_failed: boolean
}

export interface AugVsRealCoin {
  eurio_id: string
  numista_id: number | null
  num_real: number
  num_aug: number
  cosine: number | null
  distance: number | null
  real_samples: string[]
  aug_samples: string[]
  skipped_reason: string | null
}

export interface AugVsRealSummary {
  num_coins: number
  mean_cosine: number | null
  min_cosine: number | null
  max_cosine: number | null
}

export interface AugVsRealReport {
  iteration_id: string
  dino_version: string
  computed_at: string | null
  summary: AugVsRealSummary
  per_coin: AugVsRealCoin[]
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

export type TrainingProgressPhase =
  | 'unknown'
  | 'bake'
  | 'training'
  | 'training_done'
  | 'export'
  | 'benchmark'
  | 'done'
  | 'failed'

export interface TrainingProgress {
  schema_version: number
  iteration_id: string
  phase: TrainingProgressPhase
  epoch_current?: number | null
  epochs_total?: number | null
  loss_current?: number | null
  loss_best?: number | null
  started_at?: string | null
  elapsed_seconds?: number | null
  eta_seconds?: number | null
  device?: string | null
  augmentations_runtime?: 'disabled' | 'legacy_compose' | null
  updated_at?: string | null
  log_tail: string[]
  error?: string | null
}

export interface RuntimeInfo {
  host_os: string
  arch: string
  cpu_brand: string
  torch_version: string
  backend: 'cuda' | 'mps' | 'cpu'
  device: string
  num_cuda_devices: number
  gpu_name: string | null
  cuda_version: string | null
  dataloader_workers: number
  hint: string
}

export type DrawerState = 'empty' | 'partial' | 'ready' | 'running'

export interface CohortProgressC1 {
  state: DrawerState
  total_coins: number
  missing_obverse: string[]
}

export interface CohortProgressC2 {
  state: DrawerState
  expected_per_coin: number
  fully_captured: number
  partial: number
  missing: number
  per_coin_missing: Array<{ eurio_id: string, missing_steps: string[] }>
}

export interface CohortProgress {
  c1: CohortProgressC1
  c2: CohortProgressC2
}

export interface IterationProgressI1 {
  state: DrawerState
  recipe_id: string | null
  recipe_name: string | null
  variant_count: number
}

export interface IterationProgressI2Coin {
  eurio_id: string
  numista_id: number | null
  baked: number
  expected: number
  skipped_reason: string | null
}

export interface IterationProgressI2 {
  state: DrawerState
  total_expected: number
  total_baked: number
  per_coin: IterationProgressI2Coin[]
}

export interface IterationProgressI3 {
  state: DrawerState
  status: IterationStatus
  training_run_id: string | null
  benchmark_run_id: string | null
  started_at: string | null
  finished_at: string | null
  failure_reason: string | null
}

export interface IterationProgressI4Studio {
  state: DrawerState
  r_at_1: number | null
}

export interface IterationProgressI4AugVsReal {
  state: DrawerState
  computed_at: string | null
  mean_cosine: number | null
}

export interface IterationProgressI4TestApp {
  state: DrawerState
  model_ready: boolean
  tflite_present: boolean
}

export interface IterationProgressI4LiveTests {
  state: DrawerState
  total: number
  recall_at_1: number | null
}

export interface IterationProgressI4 {
  state: DrawerState
  studio: IterationProgressI4Studio
  aug_vs_real: IterationProgressI4AugVsReal
  test_app: IterationProgressI4TestApp
  live_tests: IterationProgressI4LiveTests
}

export interface IterationProgress {
  i1: IterationProgressI1
  i2: IterationProgressI2
  i3: IterationProgressI3
  i4: IterationProgressI4
}

export interface BakeReport {
  eurio_id: string
  numista_id: number | null
  written: number
  sources_used: number
  skipped_reason: string | null
}

export interface BakeResult {
  ok: boolean
  total_baked: number
  reports: BakeReport[]
}

export interface CohortTestBuildInfo {
  cohort_name: string
  iteration_id: string
  iteration_name: string
  model_ready: boolean
  command: string | null
  bundle_path: string
  tflite_present: boolean
  reason: string | null
}

// ─── Live tests (Sprint 4) ─────────────────────────────────────────────────

export type LiveTestCondition = 'bright' | 'dim' | 'tilt'

export interface LiveTestTopMatch {
  eurio_id: string
  similarity: number
}

export interface LiveTestEntry {
  iteration_id: string
  test_idx: number
  expected_eurio_id: string
  condition: LiveTestCondition
  predicted_top3: LiveTestTopMatch[]
  predicted_top1: string | null
  similarity_top1: number | null
  is_correct: boolean
  error: string | null
  ts: string
  synced_at: string | null
}

export interface LiveTestsSummary {
  total: number
  correct: number
  recall_at_1: number | null
  studio_r_at_1: number | null
  delta: number | null
}

export interface LiveTestsReport {
  iteration_id: string
  cohort_id: string
  cohort_name: string
  conditions: LiveTestCondition[]
  tests: LiveTestEntry[]
  matrix: Record<string, Partial<Record<LiveTestCondition, LiveTestEntry>>>
  summary: LiveTestsSummary
  log_present: boolean
  log_path: string
}

export interface LiveTestsSyncResult {
  iteration_id: string
  cohort_id: string
  log_path: string
  inserted: number
  skipped_dupe: number
  parse_errors: string[]
  summary: LiveTestsSummary
}

// ─── Benchmark run detail (ex-features/benchmark, kept here only for IterationDetailPage) ─

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

export interface BenchmarkRunDetail {
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
  status: 'running' | 'completed' | 'failed'
  error: string | null
  started_at: string | null
  finished_at: string | null
  eurio_ids: string[]
  per_coin: BenchmarkPerCoin[]
  per_condition: Record<string, Record<string, { r_at_1: number; r_at_3: number; num_photos: number }>>
  confusion: Record<string, Record<string, number>>
  top_confusions: BenchmarkTopConfusion[]
}

// ─── Dashboard (Sprint 5) ──────────────────────────────────────────────────

export interface DashboardTopRecipe {
  recipe_id: string
  recipe_name: string | null
  zone: 'green' | 'orange' | 'red' | null
  n_iterations: number
  mean_live_r_at_1: number | null
  mean_studio_r_at_1: number | null
  iteration_ids: string[]
}

export interface DashboardDifficultCoin {
  eurio_id: string
  mean_live_r_at_1: number
  n_iterations: number
  iteration_ids: string[]
}

export interface DashboardDistanceBin {
  range: string
  count: number
}

export interface DashboardReport {
  top_recipes: DashboardTopRecipe[]
  difficult_coins: DashboardDifficultCoin[]
  distance_distribution: {
    total: number
    bins: DashboardDistanceBin[]
    threshold_difficult_r_at_1: number
    min_iterations_for_difficult: number
  }
  totals: {
    n_cohorts: number
    n_iterations: number
    n_completed: number
  }
}

export interface PurgeAugmentationsResult {
  iteration_id: string
  cohort_id: string
  removed_dirs: string[]
  staging_root_removed: boolean
  skipped: string[]
}

export interface PurgeTestBundleResult {
  iteration_id: string
  cohort_id: string
  bundle_path: string
  removed: boolean
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
