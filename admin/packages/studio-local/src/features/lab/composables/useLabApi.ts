// Fetch wrappers for the /lab/* subsystem served by the local ML API.
//
// Same host as the training composable (http://127.0.0.1:8042).

import { ML_API } from '@/features/training/composables/useTrainingApi'
import { eurioApi } from '@/shared/api/eurio-api'
import type {
  AugVsRealReport,
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

// Garde-fou « prêt à entraîner » (lecture seule). Le staging est IMPLICITE :
// une itération entraîne cohort.eurio_ids. Renvoie le preflight (classes pas
// prêtes) pour bloquer « Nouvelle itération » côté front.
export async function fetchTrainingReadiness(
  cohortId: string,
): Promise<import('../types').CohortReadiness> {
  return json<import('../types').CohortReadiness>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/training-readiness`,
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

// ─── eBay — sourcing & funnel (§C3) ─────────────────────────────────────

/**
 * eBay sourcing + funnel scrape → review scopé cohort (§C3). Read-only, zéro
 * appel eBay. per_coin = tail post-attribution + sourcing (train/réels) ;
 * head.groups = pré-attribution par groupe ; + quota/scrapable_groups.
 */
export async function fetchCohortFunnelStatus(
  cohortId: string,
): Promise<import('../types').CohortFunnelStatus> {
  return json<import('../types').CohortFunnelStatus>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/funnel-status`,
  )
}

/**
 * Résumé des rejets eBay scopé aux pièces de la cohort (C2).
 * Raisons normalisées (commemo_in_standard_run:* → une seule classe).
 * Widget §C3 — alimente rescue_total / noise_total / ambiguous_total.
 */
export async function fetchCohortDiscardSummary(
  cohortId: string,
): Promise<import('../types').CohortDiscardSummary> {
  return json<import('../types').CohortDiscardSummary>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/discard-summary`,
  )
}

/**
 * Compteurs dédup eBay scopé cohort (C8) — lecture seule, zéro appel eBay.
 * n_unique_seen = discovery_log global ; discarded scopé aux eurio_ids de la cohort.
 */
export async function fetchCohortDedupStatus(
  cohortId: string,
): Promise<import('../types').CohortDedupStatus> {
  return json<import('../types').CohortDedupStatus>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/dedup-status`,
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
  cohortId: string,
): Promise<import('../types').EbayScrapeTriggerResult> {
  // `cohort_id` accompagne le `target_eurio_id` UNIQUEMENT comme label de la
  // trace cohort_jobs (BUG-3) — le backend ne l'expanse pas en groupes quand un
  // target est présent (cf. sources_routes.trigger_run). Périmètre scrapé = la
  // seule pièce ciblée, le quota n'est pas affecté.
  return json<import('../types').EbayScrapeTriggerResult>(
    `/sources/ebay/runs`,
    {
      method: 'POST',
      body: JSON.stringify({ target_eurio_id: targetEurioId, cohort_id: cohortId }),
    },
  )
}

/**
 * Re-crope en arrière-plan les raws eBay zéro-crop d'UNE pièce (census + gate
 * anti-fragment). Additif & sûr : ne touche que les raws sans crop présent,
 * crops créés en training_eligible=0 → review. Ne consomme PAS le quota eBay
 * (recrop local, pas de nouvelle découverte). Le front poll funnel-status.
 */
export async function triggerRecropZeroCoin(
  cohortId: string,
  eurioId: string,
): Promise<{ status: string; run_id: string; eurio_id: string }> {
  return json<{ status: string; run_id: string; eurio_id: string }>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/coins/${encodeURIComponent(eurioId)}/recrop-zero`,
    { method: 'POST' },
  )
}

// ─── QA crops d'entraînement par classe (C3, Direction A) ────────────────
//
// La LISTE (état-DB-portable : crops/classes/compteurs) se lit désormais sur
// le VPS canonique via `eurioApi` — même chemin public que l'ancien serving
// local (`/lab/cohorts/{id}/training-crops`), juste une autre base URL (auth
// Bearer PAT en local, cookie OIDC en hébergé, cf. shared/api/eurio-api.ts).
// Les DÉRIVÉS GPU (R@1/confused_with/intruder_*) et FS
// (has_numista_ref/n_bce_ref) restent LOCAUX (`/lab/cohorts/{id}/training-
// overlay`, ML_API, full-server only — jamais servi sur l'image lean, le VPS
// n'a pas de GPU) et se mergent côté front par asset_id/class_id (cf.
// useCohortTrainingCropsQuery dans useLabQueries.ts).

/** État-DB-portable de la cohorte (VPS canonique, scope `lab:read`). */
export async function fetchCohortTrainingCropsState(
  cohortId: string,
): Promise<import('../types').CohortTrainingCropsState> {
  return eurioApi.get<import('../types').CohortTrainingCropsState>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/training-crops`,
  )
}

/** Overlay dérivé GPU+FS (LOCAL, ML_API) — absent en hébergé ou ML éteint. */
export async function fetchCohortTrainingOverlay(
  cohortId: string,
): Promise<import('../types').CohortTrainingOverlay> {
  return json<import('../types').CohortTrainingOverlay>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/training-overlay`,
  )
}

/** Inclut/exclut un crop du train (réversible). Écriture canonique → VPS
 *  (scope `review:write`, C2a `funnel_writes.py`, même chemin public). */
export async function setAssetTrainingEligible(
  assetId: string,
  eligible: boolean,
): Promise<import('../types').SetTrainingEligibleResult> {
  return eurioApi.post<import('../types').SetTrainingEligibleResult>(
    `/lab/assets/${encodeURIComponent(assetId)}/training-eligible`,
    { eligible },
  )
}

/**
 * Lance le scan Dino du Jeu d'entraînement (P1 intrus closed-set + P2 passe de
 * face sur les NULL/'unknown'). Subprocess détaché côté ML — poll
 * `fetchTrainingScanStatus`, puis recharger training-crops (badges mergés).
 */
export async function startTrainingScan(
  cohortId: string,
): Promise<{ status: string; scan_id: string; n_total: number }> {
  return json<{ status: string; scan_id: string; n_total: number }>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/training-scan`,
    { method: 'POST' },
  )
}

/** Statut du dernier scan (persisté — `idle` si aucun scan n'a jamais tourné). */
export async function fetchTrainingScanStatus(
  cohortId: string,
): Promise<import('../types').TrainingScanStatus> {
  return json<import('../types').TrainingScanStatus>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/training-scan/status`,
  )
}

/**
 * « Repasser en reviewer » : un crop promu au train qu'on veut retrancher.
 * Remet needs_review + training_eligible=0 et ré-enfile une row review_queue
 * ouverte → le crop réapparaît dans l'écran Review (§C4). Écriture canonique
 * → VPS (C2a `funnel_writes.py`, même chemin public).
 */
export async function reopenAssetReview(
  assetId: string,
): Promise<import('../types').ReopenReviewResult> {
  return eurioApi.post<import('../types').ReopenReviewResult>(
    `/lab/assets/${encodeURIComponent(assetId)}/reopen-review`,
  )
}

/**
 * « Accepter au train » un crop needs_review : décision de review one-clic qui
 * confirme le crop dans sa classe (manual + eligible), le sort de « À reviewer »
 * et ferme sa file de review. Symétrique de reopenAssetReview. Écriture
 * canonique → VPS (C2a `funnel_writes.py`, même chemin public).
 */
export async function acceptAssetTraining(
  assetId: string,
): Promise<import('../types').AcceptTrainingResult> {
  return eurioApi.post<import('../types').AcceptTrainingResult>(
    `/lab/assets/${encodeURIComponent(assetId)}/accept-training`,
  )
}

/**
 * Réassigne un crop à une autre pièce (eurio_id) — redirige un intrus vers la
 * bonne classe. Ne touche que `image_assets.eurio_id` (training_eligible/face
 * préservés) ; l'asset change de classe au prochain read du Jeu d'entraînement.
 * Écriture canonique → VPS (C2a `funnel_writes.py`, même chemin public).
 */
export async function reassignAsset(
  assetId: string,
  eurioId: string,
): Promise<import('../types').ReassignAssetResult> {
  return eurioApi.post<import('../types').ReassignAssetResult>(
    `/lab/assets/${encodeURIComponent(assetId)}/reassign`,
    { eurio_id: eurioId },
  )
}

/**
 * « Faux positif — garde-le au train » : override humain du badge intrus, sans
 * changer de classe ni exclure. Le verdict du dernier scan passe `dismissed=1`
 * (l'audit `is_intruder` reste) → le crop quitte la sous-liste « Intrus ? ».
 */
export async function dismissIntruder(
  assetId: string,
  cohortId: string,
): Promise<{ asset_id: string; dismissed: boolean }> {
  // cohort_id : scope le dismiss au scan de la cohorte affichée (un crop peut
  // être scanné dans plusieurs cohortes — on ne touche que la bonne).
  return json<{ asset_id: string; dismissed: boolean }>(
    `/lab/assets/${encodeURIComponent(assetId)}/intruder-dismiss`
    + `?cohort_id=${encodeURIComponent(cohortId)}`,
    { method: 'POST' },
  )
}

/**
 * Détail des candidates au rescue, groupées par eurio_id (C5).
 * Contrairement à fetchCohortDiscardSummary (agrégat normalisé §C3), renvoie
 * le détail par pièce avec les IDs individuels pour l'action 1-clic Reclasser.
 */
export async function fetchRescueCandidates(
  cohortId: string,
): Promise<import('../types').RescueCandidates> {
  return json<import('../types').RescueCandidates>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/rescue-candidates`,
  )
}

/**
 * Reclasse un discard eBay vers son eurio_id cible (C5).
 * Insère dans source_images si absent (dédup sur source+source_ref).
 * Idempotent : un second appel retourne already_existed=true.
 */
export async function rescueDiscard(
  discardId: string,
): Promise<import('../types').RescueResult> {
  return json<import('../types').RescueResult>(
    `/lab/discarded/${encodeURIComponent(discardId)}/rescue`,
    { method: 'POST', body: '{}' },
  )
}

/**
 * Retourne les runs eBay en cours (status=running). Utilisé pour le badge live
 * dans CohortDrawerEbay (polling 3s). Renvoie une liste vide si aucun run actif.
 */
export async function fetchEbayRunningRuns(): Promise<import('../types').EbayRunLive[]> {
  return json<import('../types').EbayRunLive[]>(
    '/sources/ebay/runs?status=running&limit=5',
  )
}

/**
 * Jobs cohorte observables (scrape/recrop) depuis la table cohort_jobs (B2).
 * Source du statut + barre de progression in-row du cockpit (remplace le badge
 * global + le thread mémoire). Récents d'abord.
 */
export async function fetchCohortJobs(
  cohortId: string,
): Promise<import('../types').CohortJob[]> {
  const res = await json<{ jobs: import('../types').CohortJob[] }>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/jobs`,
  )
  return res.jobs
}

// ─── Iterations ────────────────────────────────────────────────────────

export async function fetchIterations(cohortId: string): Promise<IterationDetail[]> {
  return json<IterationDetail[]>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/iterations`,
  )
}

// ─── Itérations canoniques (toutes machines) + origine (R3) ────────────────

/** Forme brute renvoyée par le canonique `GET /iterations` : le résumé
 *  (recette + métriques) est imbriqué sous `summary`, l'origine sous `created_on`. */
interface CanonicalIterationRow extends Omit<IterationDetail, 'recipe_name' | 'benchmark_summary' | 'training_summary'> {
  created_on: string | null
  summary: {
    recipe_name: string | null
    benchmark_summary: IterationDetail['benchmark_summary']
    training_summary: IterationDetail['training_summary']
  } | null
}

/** Aplatit une row canonique vers la forme `IterationDetail` du front. */
function mapCanonicalIteration(row: CanonicalIterationRow): IterationDetail {
  const { summary, ...rest } = row
  return {
    ...rest,
    recipe_name: summary?.recipe_name ?? null,
    benchmark_summary: summary?.benchmark_summary ?? null,
    training_summary: summary?.training_summary ?? null,
    created_on: row.created_on ?? null,
  }
}

/** Itérations d'une cohorte vues par le CANONIQUE (Mac + PC). Lecture légère
 *  (scope `lab:read`), sert la liste multi-machines de la page cohorte. */
export async function fetchCanonicalIterations(cohortId: string): Promise<IterationDetail[]> {
  const rows = await eurioApi.get<CanonicalIterationRow[]>(
    `/iterations?cohort_id=${encodeURIComponent(cohortId)}`,
  )
  return rows.map(mapCanonicalIteration)
}

/** Origine machine (mac/pc) de CE poste de calcul, via le ML local `/whoami`. */
export async function fetchLocalMachine(): Promise<string | null> {
  const res = await json<{ machine: string | null }>('/whoami')
  return res.machine ?? null
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

export async function fetchIterationSources(
  cohortId: string,
  iterationId: string,
): Promise<import('../types').IterationSources> {
  return json<import('../types').IterationSources>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/iterations/${encodeURIComponent(iterationId)}/sources`,
  )
}

// ─── Augmentation bake : détaché + poll (refacto-ml chunk 4) ────────────
// Les endpoints `/bake`, `/augmentations/regenerate` et `/preview-iteration`
// renvoient 202 + un job_id ; le bake tourne en subprocess détaché (survit au
// reload de l'API). On poll `…/augmentations/job` jusqu'à terminal pour que
// l'`isPending` de la mutation couvre toute la durée du bake (spinner inchangé).

export interface AugmentationJob {
  status: 'idle' | 'running' | 'done' | 'failed' | 'skipped'
  n_total: number | null
  n_done: number
  note: string | null
  error: string | null
}

export async function fetchAugmentationJob(
  cohortId: string,
  iterationId: string,
): Promise<AugmentationJob> {
  return json<AugmentationJob>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/iterations/${encodeURIComponent(iterationId)}/augmentations/job`,
  )
}

const _sleep = (ms: number) => new Promise<void>(r => setTimeout(r, ms))

async function waitForAugmentationBake(
  cohortId: string,
  iterationId: string,
): Promise<void> {
  // Le job est créé synchroniquement par le 202 → la 1re lecture le voit déjà.
  // Cap dur (~1h à 1s) pour ne jamais boucler indéfiniment.
  for (let i = 0; i < 3600; i++) {
    const job = await fetchAugmentationJob(cohortId, iterationId)
    if (job.status === 'done' || job.status === 'skipped') return
    if (job.status === 'failed')
      throw new Error(job.error || 'Bake des augmentations échoué')
    await _sleep(1000)
  }
  throw new Error('Bake des augmentations : délai dépassé')
}

export async function bakeIterationAugmentations(
  cohortId: string,
  iterationId: string,
): Promise<void> {
  await json(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/iterations/${encodeURIComponent(iterationId)}/bake`,
    { method: 'POST', body: '{}' },
  )
  await waitForAugmentationBake(cohortId, iterationId)
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
): Promise<void> {
  await json(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/iterations/${encodeURIComponent(iterationId)}/augmentations/regenerate`,
    { method: 'POST', body: '{}' },
  )
  await waitForAugmentationBake(cohortId, iterationId)
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
  job_id: string
  status: string
}

export async function previewIteration(
  cohortId: string,
  payload: { recipe_id: string | null; variant_count?: number },
): Promise<PreviewIterationResult> {
  // 202 + job_id ; le bake détaché tourne en arrière-plan. L'appelant qui veut
  // attendre la fin poll via `waitForAugmentationBake(cohortId, result.iteration_id)`.
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
