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

// ─── eBay cohort sourcing (quota + groupes scrapables) ──────────────────

export interface EbayQuotaInfo {
  ok: boolean
  estimate: number
  remaining: number
  limit: number
  avg_calls_per_eurio_id: number
  max_safe_batch: number
}

export interface CohortScrapableGroup {
  denomination: number
  country: string
  // null pour un groupe standard (kind='standard') : le design couvre
  // toutes les années, la recherche eBay est sans millésime.
  year: number | null
  n_coins: number
  kind: 'commemorative' | 'standard'
}

export interface EbayScrapeTriggerResult {
  run_id: string
  status: string
  source_id: string
  kind: string
  non_scrapable: string[] | null
}

/**
 * Sous-ensemble de RunSnapshot pour le badge run live dans CohortDrawerEbay.
 * Peuplé via GET /sources/ebay/runs?status=running (SourceRunListItem étendu).
 */
export interface EbayRunLive {
  id: string
  status: string          // 'running'
  current_step: string | null
  started_at: string
  n_raws_added: number
  n_crops_added: number
  n_errors: number
}

// ─── eBay — sourcing & funnel (§C3, scopé cohort) ────────────────────────
// Voir GET /lab/cohorts/{id}/funnel-status (ml/api/lab_routes.py). Deux mailles :
// per_coin = TAIL précis (post-attribution) + sourcing (train/réels) ;
// head.groups = PRÉ-attribution par (pays, année, kind).

export interface CohortFunnelRoute {
  route_decision: string | null
  route_reason: string | null
  n: number
}

export interface CohortFunnelCoin {
  eurio_id: string
  numista_id: number | null
  scrapable: boolean
  n_source_images: number // listings retenus (attribués à ce coin)
  n_crops: number
  // Téléchargement (MinIO write-through) : success vs failed (retry-able)
  n_downloaded: number        // source_images avec download_status='success'
  n_download_failed: number   // source_images avec download_status='failed'
  n_zero_crops: number        // raws téléchargés SANS aucun crop → candidats recrop
  by_route_decision: CohortFunnelRoute[]
  n_pending: number
  n_review_single: number    // route_decision (intention) — figé après décision
  n_review_lot: number       // route_decision (intention) — figé après décision
  n_open_review_single: number  // review_queue.status='open' kind='single' — RESTE à reviewer
  n_open_review_lot: number     // review_queue.status='open' kind='lot' — RESTE à reviewer
  n_auto: number
  n_rejected: number
  n_unrouted: number
  // État CANONIQUE (image_state_current) — source honnête, persistée, qui
  // remplace les heuristiques route_decision figées (C3). À PRÉFÉRER pour
  // l'affichage : n_in_review (file vivante) > n_review_single+lot (gelés).
  state_counts: Record<string, number> // {detected, queued, resolved, rejected, orphaned, …}
  n_in_review: number          // queued + in_review — file de review VIVANTE
  n_resolved: number           // crops tranchés (resolution_status='manual')
  n_resolved_training: number  // tranchés ET training_eligible=1 — « validés »
  n_orphaned: number           // crops sans file ni résolution (jadis invisibles → ~0)
  // Sourcing (bout du tunnel, fusionné depuis l'ancien §C3) : crops reviewés
  // training-eligible + sources réelles distinctes (obverse + eBay reviewé) ;
  // `enough` = ≥ min_real_sources (sinon l'augmentation gonflerait, §C5).
  n_training_eligible: number
  n_real_sources: number  // = n_seed (crops eBay validés + obverse Numista + réfs)
  enough: boolean         // n_training_eligible >= min_real_sources
  below_real_floor: boolean // n_training_eligible < min_real_sources (diversité faible)
  // Cible & funnel (C3) : facteur d'augmentation DYNAMIQUE = ceil(100/seed).
  n_numista_ref: number   // 1 si obverse Numista présent (FS datasets/<nid>)
  n_bce_ref: number       // réfs canoniques officielles BCE/EUR-Lex présentes sur disque
  n_seed: number          // sources réelles distinctes (eBay validés + numista + refs)
  aug_factor: number      // ceil(100 / max(seed,1)) — facteur uniforme
  n_projected: number     // aug_factor * n_seed (≥ 100 dès seed ≥ 1)
  gap_to_target: number   // max(0, training_target - n_projected), informatif
  never_scraped: boolean  // n_source_images == 0
  // Run le plus récent ayant produit des listings pour ce coin → cible du
  // deep-link bench. n_runs > 1 = limite v1 connue (on linke le dernier).
  latest_run_id: string | null
  latest_run_started_at: string | null
  n_runs: number
}

export interface CohortFunnelDiscardReason {
  reason: string
  n: number
}

export interface CohortFunnelHeadGroup {
  country: string | null
  year: number | null
  denomination: number
  kind: 'commemorative' | 'standard'
  n_referential_coins: number
  // Funnel de découverte (discovery_searches, keyé filters_json.group).
  n_searches: number
  n_summaries: number // N0 — itemSummaries bruts
  n_after_groups: number // N1
  n_raw_results: number // N2 — post theme-token
  n_kept_results: number // N3 — post accept_listing
  // Lentille attribution (source_images attribués aux coins du groupe).
  n_attributed_source_images: number
  n_discarded_attributed: number
  discarded_by_reason: CohortFunnelDiscardReason[]
}

// C8 cohort-pipeline : compteurs dédup eBay scopé cohort (GET /lab/cohorts/{id}/dedup-status).
// discovery_log est global (pas de FK cohort) ; discarded_listings scopé via target_eurio_id.
export interface CohortDedupStatus {
  cohort_id: string
  // discovery_log global (pas de FK cohort)
  scope_note: string
  n_unique_seen: number          // discovery_log eBay global (toutes cohortes)
  // discarded_listings scopé aux eurio_ids de la cohort
  n_discarded_total: number
  n_discarded_unique: number
  n_duplicates: number           // total - unique
  n_absent_from_discovery: number // unique non couverts par discovery_log
  pct_absent: number | null      // % absents (null si 0 discardés)
}

// Crops validés (training_eligible=1) scrapés sous un groupe de la cohort mais
// ré-attribués en review à une pièce SŒUR hors cohort (rescue cross-classe).
// Training valide pour la sœur — rendu visible pour que le travail ne paraisse
// pas perdu, jamais compté dans le seed d'une pièce cohort.
export interface RescuedToSister {
  source_coin: string       // pièce cohort sous laquelle le listing a été scrapé
  sister_eurio_id: string   // pièce réelle (hors cohort) attribuée en review
  n: number
}

export interface CohortFunnelStatus {
  cohort_id: string
  per_coin: CohortFunnelCoin[]
  rescued_to_sisters: RescuedToSister[]
  head: {
    groups: CohortFunnelHeadGroup[]
    run_ids: string[]
  }
  // Sourcing cohort-level (fusionné depuis l'ancien §C3) : groupes de découverte
  // + quota offline du scrape cohort. Aucun appel eBay.
  scrapable_groups: CohortScrapableGroup[]
  non_scrapable: string[]
  quota: EbayQuotaInfo | null
  min_real_sources: number
  training_target: number
}

// C2 cohort-pipeline : résumé des rejets eBay scopé cohort (GET /lab/cohorts/{id}/discard-summary).
export interface DiscardSummaryRow {
  reason_class: string
  n: number
  is_rescue_candidate: 1 | 0 | null
}

// C5 cohort-pipeline : détail rescue par pièce (GET /lab/cohorts/{id}/rescue-candidates).
export interface DiscardReasonRow {
  reason: string
  n: number
  is_rescue_candidate: boolean
  rescue_eurio_id: string | null
  // IDs individuels des discarded_listings à rescue (présents si is_rescue_candidate=true)
  discard_ids: string[]
}

export interface DiscardSummaryClass {
  eurio_id: string
  total_discards: number
  by_reason: DiscardReasonRow[]
  rescue_count: number
}

export interface RescueCandidates {
  cohort_id: string
  per_class: DiscardSummaryClass[]
  noise_total: number
  noise_by_reason: Array<{ reason: string; n: number }>
}

// Réponse POST /lab/discarded/{id}/rescue
export interface RescueResult {
  discard_id: string
  eurio_id: string
  n_persisted: number
  already_existed: boolean
}

export interface CohortDiscardSummary {
  cohort_id: string
  total: number
  rows: DiscardSummaryRow[]
  rescue_total: number
  noise_total: number
  ambiguous_total: number
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
  | 'benchmark_failed'
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
  error: string | null
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
