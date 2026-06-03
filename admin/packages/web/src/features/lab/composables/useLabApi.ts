// Fetch wrappers for the /lab/* subsystem served by the local ML API.
//
// Same host as the training composable (http://127.0.0.1:8042).

import { ML_API } from '@/features/training/composables/useTrainingApi'
import type {
  AugVsRealReport,
  BakeResult,
  CohortCaptureManifest,
  CohortCreatePayload,
  CohortCsvResult,
  CohortProgress,
  CohortStatus,
  CohortSummary,
  CohortSyncResult,
  IterationAugmentations,
  IterationCreatePayload,
  IterationDetail,
  IterationProgress,
  RegenerateAugmentationsResult,
  RunnerStatus,
  RuntimeInfo,
  SensitivityEntry,
  StopIterationResult,
  TrainingProgress,
  TrajectoryPoint,
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

// ─── Cohorts ───────────────────────────────────────────────────────────

export async function fetchCohorts(opts?: {
  zone?: string | null
  status?: CohortStatus | null
}): Promise<CohortSummary[]> {
  const params = new URLSearchParams()
  if (opts?.zone) params.set('zone', opts.zone)
  if (opts?.status) params.set('status', opts.status)
  const qs = params.toString() ? `?${params.toString()}` : ''
  return json<CohortSummary[]>(`/lab/cohorts${qs}`)
}

export async function fetchCohort(idOrName: string): Promise<CohortSummary> {
  return json<CohortSummary>(`/lab/cohorts/${encodeURIComponent(idOrName)}`)
}

export async function createCohort(payload: CohortCreatePayload): Promise<CohortSummary> {
  return json<CohortSummary>('/lab/cohorts', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateCohort(
  id: string,
  patch: Partial<Pick<CohortCreatePayload, 'name' | 'description' | 'zone'>>,
): Promise<CohortSummary> {
  return json<CohortSummary>(`/lab/cohorts/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify(patch),
  })
}

export async function deleteCohort(id: string): Promise<void> {
  await json<{ deleted: boolean }>(`/lab/cohorts/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
}

export async function addCoinsToCohort(
  cohortId: string,
  eurioIds: string[],
): Promise<CohortSummary> {
  return json<CohortSummary>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/coins`,
    { method: 'POST', body: JSON.stringify({ eurio_ids: eurioIds }) },
  )
}

export async function removeCoinFromCohort(
  cohortId: string,
  eurioId: string,
): Promise<CohortSummary> {
  return json<CohortSummary>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/coins/${encodeURIComponent(eurioId)}`,
    { method: 'DELETE' },
  )
}

export async function cloneCohort(
  cohortId: string,
  payload: { name: string; description?: string | null },
): Promise<CohortSummary> {
  return json<CohortSummary>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/clone`,
    { method: 'POST', body: JSON.stringify(payload) },
  )
}

// ─── Captures (cohort capture flow) ────────────────────────────────────

export async function fetchCohortProgress(cohortId: string): Promise<CohortProgress> {
  return json<CohortProgress>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/progress`,
  )
}

export async function fetchCohortCaptures(cohortId: string): Promise<CohortCaptureManifest> {
  return json<CohortCaptureManifest>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/captures/status`,
  )
}

export async function generateCohortCsv(cohortId: string): Promise<CohortCsvResult> {
  return json<CohortCsvResult>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/captures/csv`,
    { method: 'POST', body: '{}' },
  )
}

export async function syncCohortCaptures(
  cohortId: string,
  opts: { pull_dir?: string; overwrite?: boolean } = {},
): Promise<CohortSyncResult> {
  return json<CohortSyncResult>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/captures/sync`,
    { method: 'POST', body: JSON.stringify(opts) },
  )
}

// ─── eBay cohort status (chunk 03b) ────────────────────────────────────

export async function fetchCohortEbayStatus(
  cohortId: string,
): Promise<import('../types').CohortEbayStatus> {
  return json<import('../types').CohortEbayStatus>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/ebay-status`,
  )
}

/**
 * Trigger a cohort-scoped eBay scrape via the sources pipeline.
 * Consumes the user's eBay quota — call only on explicit user action.
 * The backend expands the cohort to its discovery groups (cohort_id).
 */
export async function triggerCohortEbayScrape(
  cohortId: string,
): Promise<import('../types').EbayScrapeTriggerResult> {
  return json<import('../types').EbayScrapeTriggerResult>(
    `/sources/ebay/runs`,
    { method: 'POST', body: JSON.stringify({ cohort_id: cohortId }) },
  )
}

/**
 * Rescrape eBay ciblé sur UNE pièce (§C5). Le backend résout le `target_eurio_id`
 * vers son groupe de découverte (EbayAdapter.discover). Consomme le quota eBay
 * (préflight 409 si insuffisant) — appel sur action explicite uniquement.
 */
export async function triggerCoinEbayScrape(
  targetEurioId: string,
): Promise<import('../types').EbayScrapeTriggerResult> {
  return json<import('../types').EbayScrapeTriggerResult>(
    `/sources/ebay/runs`,
    { method: 'POST', body: JSON.stringify({ target_eurio_id: targetEurioId }) },
  )
}

// ─── Iterations ────────────────────────────────────────────────────────

export async function fetchIterations(cohortId: string): Promise<IterationDetail[]> {
  return json<IterationDetail[]>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/iterations`,
  )
}

export async function fetchIteration(cohortId: string, iterationId: string): Promise<IterationDetail> {
  return json<IterationDetail>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/iterations/${encodeURIComponent(iterationId)}`,
  )
}

export async function createIteration(
  cohortId: string,
  payload: IterationCreatePayload,
): Promise<IterationDetail> {
  return json<IterationDetail>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/iterations`,
    { method: 'POST', body: JSON.stringify(payload) },
  )
}

export async function updateIteration(
  cohortId: string,
  iterationId: string,
  patch: {
    notes?: string | null
    verdict_override?: string | null
    recipe_id?: string | null
    variant_count?: number | null
  },
): Promise<IterationDetail> {
  return json<IterationDetail>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/iterations/${encodeURIComponent(iterationId)}`,
    { method: 'PUT', body: JSON.stringify(patch) },
  )
}

export async function fetchIterationProgress(
  cohortId: string,
  iterationId: string,
): Promise<IterationProgress> {
  return json<IterationProgress>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/iterations/${encodeURIComponent(iterationId)}/progress`,
  )
}

export async function bakeIterationAugmentations(
  cohortId: string,
  iterationId: string,
): Promise<BakeResult> {
  return json<BakeResult>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/iterations/${encodeURIComponent(iterationId)}/bake`,
    { method: 'POST', body: '{}' },
  )
}

export async function launchIterationTraining(
  cohortId: string,
  iterationId: string,
): Promise<IterationDetail> {
  return json<IterationDetail>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/iterations/${encodeURIComponent(iterationId)}/launch-training`,
    { method: 'POST', body: '{}' },
  )
}

export async function launchIterationBenchmark(
  cohortId: string,
  iterationId: string,
): Promise<IterationDetail> {
  return json<IterationDetail>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/iterations/${encodeURIComponent(iterationId)}/launch-benchmark`,
    { method: 'POST', body: '{}' },
  )
}

export async function deleteIteration(cohortId: string, iterationId: string): Promise<void> {
  await json<{ deleted: boolean }>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/iterations/${encodeURIComponent(iterationId)}`,
    { method: 'DELETE' },
  )
}

// ─── Analytics ─────────────────────────────────────────────────────────

export async function fetchTrajectory(cohortId: string): Promise<TrajectoryPoint[]> {
  return json<TrajectoryPoint[]>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/trajectory`,
  )
}

export async function fetchSensitivity(cohortId: string): Promise<SensitivityEntry[]> {
  return json<SensitivityEntry[]>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/sensitivity`,
  )
}

export async function fetchRunnerStatus(): Promise<RunnerStatus> {
  return json<RunnerStatus>('/lab/runner/status')
}

export async function fetchRuntimeInfo(): Promise<RuntimeInfo> {
  return json<RuntimeInfo>('/lab/runner/runtime-info')
}

export async function fetchTrainingProgress(
  iterationId: string,
): Promise<TrainingProgress> {
  return json<TrainingProgress>(
    `/lab/runner/training-progress/${encodeURIComponent(iterationId)}`,
  )
}

// ─── Augmentations (Sprint 1) ───────────────────────────────────────────

export async function fetchIterationAugmentations(
  cohortId: string,
  iterationId: string,
): Promise<IterationAugmentations> {
  return json<IterationAugmentations>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/iterations/${encodeURIComponent(iterationId)}/augmentations`,
  )
}

export async function regenerateIterationAugmentations(
  cohortId: string,
  iterationId: string,
): Promise<RegenerateAugmentationsResult> {
  return json<RegenerateAugmentationsResult>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/iterations/${encodeURIComponent(iterationId)}/augmentations/regenerate`,
    { method: 'POST', body: '{}' },
  )
}

export async function stopIteration(
  cohortId: string,
  iterationId: string,
): Promise<StopIterationResult> {
  return json<StopIterationResult>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/iterations/${encodeURIComponent(iterationId)}/stop`,
    { method: 'POST', body: '{}' },
  )
}

export interface PreviewIterationResult {
  iteration_id: string
  name: string
  augmentations_seed: number | null
  recipe_id: string | null
  variant_count: number
  per_coin: Array<{
    eurio_id: string
    numista_id: number | null
    written: number
    skipped_reason: string | null
  }>
}

export async function previewIteration(
  cohortId: string,
  payload: { recipe_id: string | null; variant_count?: number },
): Promise<PreviewIterationResult> {
  return json<PreviewIterationResult>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/preview-iteration`,
    { method: 'POST', body: JSON.stringify(payload) },
  )
}

// ─── Aug ↔ réelles (Sprint 2) ───────────────────────────────────────────

export async function fetchAugVsReal(
  cohortId: string,
  iterationId: string,
): Promise<AugVsRealReport> {
  return json<AugVsRealReport>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/iterations/${encodeURIComponent(iterationId)}/aug-vs-real`,
  )
}

export async function recomputeAugVsReal(
  cohortId: string,
  iterationId: string,
): Promise<AugVsRealReport> {
  return json<AugVsRealReport>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/iterations/${encodeURIComponent(iterationId)}/aug-vs-real/recompute`,
    { method: 'POST', body: '{}' },
  )
}

// ─── Cohort test app build info (Sprint 3) ──────────────────────────────

export async function fetchCohortTestBuildInfo(
  cohortId: string,
  iterationId: string,
): Promise<import('../types').CohortTestBuildInfo> {
  return json<import('../types').CohortTestBuildInfo>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/iterations/${encodeURIComponent(iterationId)}/test-app/build-info`,
  )
}

// ─── Live tests (Sprint 4) ───────────────────────────────────────────────

export async function fetchLiveTests(
  cohortId: string,
  iterationId: string,
): Promise<import('../types').LiveTestsReport> {
  return json<import('../types').LiveTestsReport>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/iterations/${encodeURIComponent(iterationId)}/live-tests`,
  )
}

export async function syncLiveTests(
  iterationId: string,
): Promise<import('../types').LiveTestsSyncResult> {
  // Cohort wildcard ``_`` — the iteration carries its own cohort_id, so the
  // pull task doesn't need to thread it through. The backend resolves both.
  return json<import('../types').LiveTestsSyncResult>(
    `/lab/cohorts/_/iterations/${encodeURIComponent(iterationId)}/live-tests/sync`,
    { method: 'POST', body: '{}' },
  )
}

// ─── Benchmark detail (migrated from features/benchmark/, Sprint 5) ─────

export async function fetchBenchmarkRunDetail(
  runId: string,
): Promise<import('../types').BenchmarkRunDetail> {
  return json<import('../types').BenchmarkRunDetail>(
    `/benchmark/runs/${encodeURIComponent(runId)}`,
  )
}

// ─── Dashboard + GC (Sprint 5) ──────────────────────────────────────────

export async function fetchDashboard(): Promise<import('../types').DashboardReport> {
  return json<import('../types').DashboardReport>('/lab/dashboard')
}

export async function purgeIterationAugmentations(
  cohortId: string,
  iterationId: string,
): Promise<import('../types').PurgeAugmentationsResult> {
  return json<import('../types').PurgeAugmentationsResult>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/iterations/${encodeURIComponent(iterationId)}/augmentations`,
    { method: 'DELETE' },
  )
}

export async function purgeIterationTestBundle(
  cohortId: string,
  iterationId: string,
): Promise<import('../types').PurgeTestBundleResult> {
  return json<import('../types').PurgeTestBundleResult>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/iterations/${encodeURIComponent(iterationId)}/test-bundle`,
    { method: 'DELETE' },
  )
}
