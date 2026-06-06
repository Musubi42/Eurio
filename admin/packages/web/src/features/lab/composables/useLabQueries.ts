// Vue Query layer over useLabApi.ts.
//
// The lab data is light (cohorts ~10s of rows, iterations 10s per cohort)
// but the page polls /lab/runner/status every few seconds and each route
// switch re-fetches everything. Wrapping in TanStack Query gives us:
//   • IDB-cached lists for instant nav
//   • automatic dedup if multiple components subscribe
//   • mutation-driven invalidation (no manual `await reload()` litter)
//
// Polling cadence: while an iteration is running we want fresh data. We
// drive that via `refetchInterval` set conditionally from the consumer.

import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, type MaybeRefOrGetter, toValue } from 'vue'
import {
  addCoinsToCohort,
  bakeIterationAugmentations,
  cloneCohort,
  createIteration,
  fetchAugVsReal,
  fetchCohort,
  fetchCohortCaptures,
  fetchCohortDedupStatus,
  fetchCohortDiscardSummary,
  fetchCohortFunnelStatus,
  fetchCohortProgress,
  fetchCohortTestBuildInfo,
  fetchCohorts,
  fetchDashboard,
  fetchIterationAugmentations,
  fetchIterationProgress,
  fetchIterations,
  fetchLiveTests,
  fetchRunnerStatus,
  fetchRuntimeInfo,
  fetchSensitivity,
  fetchTrainingProgress,
  fetchTrajectory,
  generateCohortCsv,
  launchIterationBenchmark,
  launchIterationTraining,
  purgeIterationAugmentations,
  purgeIterationTestBundle,
  recomputeAugVsReal,
  regenerateIterationAugmentations,
  removeCoinFromCohort,
  stopIteration,
  syncCohortCaptures,
  syncLiveTests,
  fetchEbayRunningRuns,
  fetchCohortJobs,
  fetchRescueCandidates,
  rescueDiscard,
  triggerCoinEbayScrape,
  triggerRecropZeroCoin,
  triggerCohortEbayScrape,
  updateIteration,
} from './useLabApi'
// Réutilise l'agrégat triage de la review (même endpoint, scopé cohort).
import { fetchTriageStats } from '@/features/review/composables/useReviewApi'
import type {
  CohortStatus,
  IterationCreatePayload,
  IterationStatus,
} from '../types'

export const LAB_KEYS = {
  cohorts: (filters: { zone?: string | null; status?: CohortStatus | null } = {}) =>
    ['lab', 'cohorts', filters] as const,
  cohort: (id: string) => ['lab', 'cohort', id] as const,
  iterations: (cohortId: string) => ['lab', 'cohort', cohortId, 'iterations'] as const,
  trajectory: (cohortId: string) => ['lab', 'cohort', cohortId, 'trajectory'] as const,
  sensitivity: (cohortId: string) => ['lab', 'cohort', cohortId, 'sensitivity'] as const,
  captures: (cohortId: string) => ['lab', 'cohort', cohortId, 'captures'] as const,
  funnelStatus: (cohortId: string) => ['lab', 'cohort', cohortId, 'funnel-status'] as const,
  discardSummary: (cohortId: string) => ['lab', 'cohort', cohortId, 'discard-summary'] as const,
  rescueCandidates: (cohortId: string) => ['lab', 'cohort', cohortId, 'rescue-candidates'] as const,
  dedupStatus: (cohortId: string) => ['lab', 'cohort', cohortId, 'dedup-status'] as const,
  triageStats: (cohortId: string) => ['lab', 'cohort', cohortId, 'triage-stats'] as const,
  jobs: (cohortId: string) => ['lab', 'cohort', cohortId, 'jobs'] as const,
  progress: (cohortId: string) => ['lab', 'cohort', cohortId, 'progress'] as const,
  iterationProgress: (cohortId: string, iterationId: string) =>
    ['lab', 'cohort', cohortId, 'iterations', iterationId, 'progress'] as const,
  augmentations: (cohortId: string, iterationId: string) =>
    ['lab', 'cohort', cohortId, 'iterations', iterationId, 'augmentations'] as const,
  augVsReal: (cohortId: string, iterationId: string) =>
    ['lab', 'cohort', cohortId, 'iterations', iterationId, 'aug-vs-real'] as const,
  buildInfo: (cohortId: string, iterationId: string) =>
    ['lab', 'cohort', cohortId, 'iterations', iterationId, 'build-info'] as const,
  liveTests: (cohortId: string, iterationId: string) =>
    ['lab', 'cohort', cohortId, 'iterations', iterationId, 'live-tests'] as const,
  dashboard: ['lab', 'dashboard'] as const,
  runner: ['lab', 'runner'] as const,
  ebayRunningRuns: ['lab', 'ebay', 'running-runs'] as const,
}

// ─── Reads ──────────────────────────────────────────────────────────────

export function useCohortsQuery(filters?: MaybeRefOrGetter<{
  zone?: string | null
  status?: CohortStatus | null
}>) {
  return useQuery({
    queryKey: computed(() => LAB_KEYS.cohorts(toValue(filters) ?? {})),
    queryFn: () => fetchCohorts(toValue(filters) ?? {}),
  })
}

export function useCohortQuery(id: MaybeRefOrGetter<string>) {
  return useQuery({
    queryKey: computed(() => LAB_KEYS.cohort(toValue(id))),
    queryFn: () => fetchCohort(toValue(id)),
    enabled: computed(() => !!toValue(id)),
  })
}

export function useIterationsQuery(
  cohortId: MaybeRefOrGetter<string>,
  opts?: { pollWhileBusy?: MaybeRefOrGetter<boolean> },
) {
  return useQuery({
    queryKey: computed(() => LAB_KEYS.iterations(toValue(cohortId))),
    queryFn: () => fetchIterations(toValue(cohortId)),
    enabled: computed(() => !!toValue(cohortId)),
    refetchInterval: computed(() => (toValue(opts?.pollWhileBusy) ? 4000 : false)),
  })
}

export function useTrajectoryQuery(cohortId: MaybeRefOrGetter<string>) {
  return useQuery({
    queryKey: computed(() => LAB_KEYS.trajectory(toValue(cohortId))),
    queryFn: () => fetchTrajectory(toValue(cohortId)),
    enabled: computed(() => !!toValue(cohortId)),
  })
}

export function useSensitivityQuery(cohortId: MaybeRefOrGetter<string>) {
  return useQuery({
    queryKey: computed(() => LAB_KEYS.sensitivity(toValue(cohortId))),
    queryFn: () => fetchSensitivity(toValue(cohortId)),
    enabled: computed(() => !!toValue(cohortId)),
  })
}

export function useCaptureManifestQuery(cohortId: MaybeRefOrGetter<string>) {
  return useQuery({
    queryKey: computed(() => LAB_KEYS.captures(toValue(cohortId))),
    queryFn: () => fetchCohortCaptures(toValue(cohortId)),
    enabled: computed(() => !!toValue(cohortId)),
    // Captures are FS-derived and only change when a sync runs — invalidate
    // explicitly on success rather than poll.
    staleTime: 60 * 60 * 1000, // 1h
  })
}

/**
 * eBay sourcing + funnel scrape → review scopé cohort (§C3). Les compteurs
 * (train, route_decision) bougent à chaque passe de review faite sur /review →
 * refetch au mount pour un compte frais au retour sur la page cohort.
 */
export function useCohortFunnelStatusQuery(cohortId: MaybeRefOrGetter<string>) {
  return useQuery({
    queryKey: computed(() => LAB_KEYS.funnelStatus(toValue(cohortId))),
    queryFn: () => fetchCohortFunnelStatus(toValue(cohortId)),
    enabled: computed(() => !!toValue(cohortId)),
    staleTime: 60 * 1000,
    refetchOnMount: 'always',
  })
}

/**
 * Badge run live pour CohortDrawerEbay : poll /sources/ebay/runs?status=running
 * toutes les 3s. La liste est vide si aucun run eBay n'est en cours.
 * Le polling s'arrête naturellement quand le composant se démonte (TanStack lifecycle).
 */
export function useEbayRunningRunsQuery() {
  return useQuery({
    queryKey: LAB_KEYS.ebayRunningRuns,
    queryFn: () => fetchEbayRunningRuns(),
    refetchInterval: 3000,
    staleTime: 0,
  })
}

/**
 * Jobs cohorte observables (scrape/recrop) — table cohort_jobs (B2). Alimente la
 * barre de progression in-row + le statut « tenté/épuisé » du bouton recrop.
 * Poll 3s tant qu'un job tourne, sinon arrêt (pas de polling inutile).
 */
export function useCohortJobsQuery(cohortId: MaybeRefOrGetter<string>) {
  return useQuery({
    queryKey: computed(() => LAB_KEYS.jobs(toValue(cohortId))),
    queryFn: () => fetchCohortJobs(toValue(cohortId)),
    enabled: computed(() => !!toValue(cohortId)),
    refetchInterval: (q) =>
      (q.state.data ?? []).some(j => j.status === 'running') ? 3000 : false,
    staleTime: 1000,
  })
}

/**
 * Résumé des rejets eBay scopé cohort (C2) — rescue / noise / ambiguous.
 * Raisons normalisées (commemo_in_standard_run:* → une seule classe).
 * Alimente le widget §C3 du tiroir CohortDrawerEbay.
 */
export function useDiscardSummaryQuery(cohortId: MaybeRefOrGetter<string>) {
  return useQuery({
    queryKey: computed(() => LAB_KEYS.discardSummary(toValue(cohortId))),
    queryFn: () => fetchCohortDiscardSummary(toValue(cohortId)),
    enabled: computed(() => !!toValue(cohortId)),
    staleTime: 60 * 1000,
    refetchOnMount: 'always',
  })
}

/**
 * Détail rescue par eurio_id (C5) — par pièce, avec les IDs individuels.
 * Distinct de useDiscardSummaryQuery (agrégat normalisé §C3) : expose les
 * discard_ids pour l'action 1-clic Reclasser dans CohortDrawerRescue.
 */
export function useRescueCandidatesQuery(cohortId: MaybeRefOrGetter<string>) {
  return useQuery({
    queryKey: computed(() => LAB_KEYS.rescueCandidates(toValue(cohortId))),
    queryFn: () => fetchRescueCandidates(toValue(cohortId)),
    enabled: computed(() => !!toValue(cohortId)),
    staleTime: 60 * 1000,
    refetchOnMount: 'always',
  })
}

/**
 * Mutation rescue 1-clic (C5) — POST /lab/discarded/{id}/rescue.
 * Invalide rescue-candidates + discard-summary + funnel-status au retour.
 */
export function useRescueDiscardMutation(cohortId: MaybeRefOrGetter<string>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (discardId: string) => rescueDiscard(discardId),
    onSuccess: () => {
      const id = toValue(cohortId)
      qc.invalidateQueries({ queryKey: LAB_KEYS.rescueCandidates(id) })
      qc.invalidateQueries({ queryKey: LAB_KEYS.discardSummary(id) })
      qc.invalidateQueries({ queryKey: LAB_KEYS.funnelStatus(id) })
    },
  })
}

/**
 * Compteurs dédup eBay scopé cohort (C8) — lecture seule.
 * n_unique_seen = discovery_log global (toutes cohortes) ; discarded scopé
 * aux eurio_ids de la cohort. Données stables → 5 min de fraîcheur.
 */
export function useCohortDedupStatusQuery(cohortId: MaybeRefOrGetter<string>) {
  return useQuery({
    queryKey: computed(() => LAB_KEYS.dedupStatus(toValue(cohortId))),
    queryFn: () => fetchCohortDedupStatus(toValue(cohortId)),
    enabled: computed(() => !!toValue(cohortId)),
    // Données statiques (pas de write depuis l'UI) — 5 min de fraîcheur suffit.
    staleTime: 5 * 60 * 1000,
    refetchOnMount: false,
  })
}

/**
 * Triage counts (queue manuelle / auto-accept / ccproxy) scopés cohort —
 * alimente les 3 cartes §C4a. Réutilise l'agrégat /review-queue/triage-stats.
 */
export function useCohortTriageStatsQuery(cohortId: MaybeRefOrGetter<string>) {
  return useQuery({
    queryKey: computed(() => LAB_KEYS.triageStats(toValue(cohortId))),
    queryFn: () => fetchTriageStats(toValue(cohortId)),
    enabled: computed(() => !!toValue(cohortId)),
    // Bougent à chaque décision de review (faite sur /review) → refetch au
    // mount pour un compte frais au retour sur la page cohort.
    staleTime: 60 * 1000,
    refetchOnMount: 'always',
  })
}

export function useCohortProgressQuery(cohortId: MaybeRefOrGetter<string>) {
  return useQuery({
    queryKey: computed(() => LAB_KEYS.progress(toValue(cohortId))),
    queryFn: () => fetchCohortProgress(toValue(cohortId)),
    enabled: computed(() => !!toValue(cohortId)),
    refetchInterval: 5000,
    staleTime: 2000,
  })
}

export function useRunnerStatusQuery() {
  return useQuery({
    queryKey: LAB_KEYS.runner,
    queryFn: () => fetchRunnerStatus(),
    refetchInterval: 5000,
    staleTime: 0,
  })
}

export function useRuntimeInfoQuery() {
  return useQuery({
    queryKey: [...LAB_KEYS.runner, 'runtime-info'] as const,
    queryFn: () => fetchRuntimeInfo(),
    staleTime: 60 * 60 * 1000,
  })
}

export function useTrainingProgressQuery(
  iterationId: MaybeRefOrGetter<string>,
  status: MaybeRefOrGetter<IterationStatus | null | undefined>,
) {
  return useQuery({
    queryKey: computed(() => [
      ...LAB_KEYS.runner,
      'training-progress',
      toValue(iterationId),
    ] as const),
    queryFn: () => fetchTrainingProgress(toValue(iterationId)),
    enabled: computed(() => {
      const s = toValue(status)
      return !!toValue(iterationId) && (s === 'training' || s === 'benchmarking')
    }),
    refetchInterval: computed(() => {
      const s = toValue(status)
      return (s === 'training' || s === 'benchmarking') ? 2000 : false
    }),
    staleTime: 1000,
  })
}

// ─── Mutations ──────────────────────────────────────────────────────────

export function useAddCoinsMutation(cohortId: MaybeRefOrGetter<string>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (eurioIds: string[]) => addCoinsToCohort(toValue(cohortId), eurioIds),
    onSuccess: () => {
      const id = toValue(cohortId)
      qc.invalidateQueries({ queryKey: LAB_KEYS.cohort(id) })
      qc.invalidateQueries({ queryKey: LAB_KEYS.captures(id) })
      qc.invalidateQueries({ queryKey: LAB_KEYS.progress(id) })
      qc.invalidateQueries({ queryKey: ['lab', 'cohorts'] })
    },
  })
}

export function useRemoveCoinMutation(cohortId: MaybeRefOrGetter<string>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (eurioId: string) => removeCoinFromCohort(toValue(cohortId), eurioId),
    onSuccess: () => {
      const id = toValue(cohortId)
      qc.invalidateQueries({ queryKey: LAB_KEYS.cohort(id) })
      qc.invalidateQueries({ queryKey: LAB_KEYS.captures(id) })
      qc.invalidateQueries({ queryKey: LAB_KEYS.progress(id) })
      qc.invalidateQueries({ queryKey: ['lab', 'cohorts'] })
    },
  })
}

export function useTriggerCohortEbayScrapeMutation(
  cohortId: MaybeRefOrGetter<string>,
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => triggerCohortEbayScrape(toValue(cohortId)),
    onSuccess: () => {
      // The scrape runs in the background; refresh counts shortly after.
      qc.invalidateQueries({ queryKey: LAB_KEYS.funnelStatus(toValue(cohortId)) })
    },
  })
}

/**
 * Rescrape eBay ciblé sur une pièce (§C5). Invalide le funnel-status de la cohort
 * au retour pour rafraîchir les compteurs une fois le run lancé.
 */
export function useTriggerCoinEbayScrapeMutation(
  cohortId: MaybeRefOrGetter<string>,
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (targetEurioId: string) =>
      triggerCoinEbayScrape(targetEurioId, toValue(cohortId)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: LAB_KEYS.funnelStatus(toValue(cohortId)) })
      qc.invalidateQueries({ queryKey: LAB_KEYS.jobs(toValue(cohortId)) })
    },
  })
}

/**
 * Recrop des zéro-crops d'UNE pièce (§WS4). Job en arrière-plan côté backend ;
 * on rafraîchit le funnel-status au retour (les crops apparaîtront au fil de
 * l'eau — un re-fetch périodique du tiroir capte la progression).
 */
export function useRecropZeroCoinMutation(
  cohortId: MaybeRefOrGetter<string>,
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (eurioId: string) => triggerRecropZeroCoin(toValue(cohortId), eurioId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: LAB_KEYS.funnelStatus(toValue(cohortId)) })
    },
  })
}

export function useCloneCohortMutation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (vars: { cohortId: string; name: string; description?: string | null }) =>
      cloneCohort(vars.cohortId, { name: vars.name, description: vars.description }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['lab', 'cohorts'] }),
  })
}

export function useGenerateCsvMutation(cohortId: MaybeRefOrGetter<string>) {
  return useMutation({
    mutationFn: () => generateCohortCsv(toValue(cohortId)),
  })
}

export function useSyncCapturesMutation(cohortId: MaybeRefOrGetter<string>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (opts: { pull_dir?: string; overwrite?: boolean } = {}) =>
      syncCohortCaptures(toValue(cohortId), opts),
    onSuccess: () => {
      const id = toValue(cohortId)
      qc.invalidateQueries({ queryKey: LAB_KEYS.captures(id) })
      qc.invalidateQueries({ queryKey: LAB_KEYS.progress(id) })
    },
  })
}

export function useIterationProgressQuery(
  cohortId: MaybeRefOrGetter<string>,
  iterationId: MaybeRefOrGetter<string>,
  status: MaybeRefOrGetter<IterationStatus | null | undefined>,
) {
  return useQuery({
    queryKey: computed(() =>
      LAB_KEYS.iterationProgress(toValue(cohortId), toValue(iterationId)),
    ),
    queryFn: () =>
      fetchIterationProgress(toValue(cohortId), toValue(iterationId)),
    enabled: computed(() => !!toValue(cohortId) && !!toValue(iterationId)),
    refetchInterval: computed(() => {
      const s = toValue(status)
      if (s === 'training' || s === 'benchmarking') return 2000
      return 5000
    }),
    staleTime: 1000,
  })
}

export function useBakeIterationMutation(
  cohortId: MaybeRefOrGetter<string>,
  iterationId: MaybeRefOrGetter<string>,
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      bakeIterationAugmentations(toValue(cohortId), toValue(iterationId)),
    onSuccess: () => {
      const cid = toValue(cohortId)
      const iid = toValue(iterationId)
      qc.invalidateQueries({ queryKey: LAB_KEYS.augmentations(cid, iid) })
      qc.invalidateQueries({ queryKey: LAB_KEYS.iterationProgress(cid, iid) })
    },
  })
}

// ─── Augmentations + Stop (Sprint 1) ────────────────────────────────────

export function useAugmentationsQuery(
  cohortId: MaybeRefOrGetter<string>,
  iterationId: MaybeRefOrGetter<string | null | undefined>,
) {
  return useQuery({
    queryKey: computed(() =>
      LAB_KEYS.augmentations(toValue(cohortId), toValue(iterationId) ?? ''),
    ),
    queryFn: () =>
      fetchIterationAugmentations(toValue(cohortId), toValue(iterationId) as string),
    enabled: computed(() => !!toValue(cohortId) && !!toValue(iterationId)),
    // Snapshot is immutable for a given (cohort, iteration) until regenerate;
    // no need to re-poll while the user is browsing the gallery.
    staleTime: 5 * 60 * 1000,
  })
}

export function useRegenerateAugmentationsMutation(
  cohortId: MaybeRefOrGetter<string>,
  iterationId: MaybeRefOrGetter<string>,
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      regenerateIterationAugmentations(toValue(cohortId), toValue(iterationId)),
    onSuccess: () => {
      const cid = toValue(cohortId)
      const iid = toValue(iterationId)
      qc.invalidateQueries({ queryKey: LAB_KEYS.augmentations(cid, iid) })
      qc.invalidateQueries({ queryKey: LAB_KEYS.iterationProgress(cid, iid) })
    },
  })
}

export function useAugVsRealQuery(
  cohortId: MaybeRefOrGetter<string>,
  iterationId: MaybeRefOrGetter<string | null | undefined>,
) {
  return useQuery({
    queryKey: computed(() =>
      LAB_KEYS.augVsReal(toValue(cohortId), toValue(iterationId) ?? ''),
    ),
    queryFn: () =>
      fetchAugVsReal(toValue(cohortId), toValue(iterationId) as string),
    enabled: computed(() => !!toValue(cohortId) && !!toValue(iterationId)),
    // Distance computation hits DINO; cache aggressively. The backend
    // already invalidates rows whose counts/version drift, so we trust
    // the server-side cache here.
    staleTime: 60 * 60 * 1000,
  })
}

export function useRecomputeAugVsRealMutation(
  cohortId: MaybeRefOrGetter<string>,
  iterationId: MaybeRefOrGetter<string>,
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      recomputeAugVsReal(toValue(cohortId), toValue(iterationId)),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: LAB_KEYS.augVsReal(toValue(cohortId), toValue(iterationId)),
      })
    },
  })
}

// ─── Cohort test app (Sprint 3) ─────────────────────────────────────────

export function useBuildInfoQuery(
  cohortId: MaybeRefOrGetter<string>,
  iterationId: MaybeRefOrGetter<string | null | undefined>,
  opts?: { iterationStatus?: MaybeRefOrGetter<string | null | undefined> },
) {
  return useQuery({
    queryKey: computed(() =>
      LAB_KEYS.buildInfo(toValue(cohortId), toValue(iterationId) ?? ''),
    ),
    queryFn: () =>
      fetchCohortTestBuildInfo(toValue(cohortId), toValue(iterationId) as string),
    enabled: computed(() => !!toValue(cohortId) && !!toValue(iterationId)),
    // Re-poll while the iteration is still running so the user sees
    // model_ready flip without a manual refresh.
    refetchInterval: computed(() => {
      const status = toValue(opts?.iterationStatus)
      return status === 'training' || status === 'benchmarking' ? 5000 : false
    }),
  })
}

export function useStopIterationMutation(cohortId: MaybeRefOrGetter<string>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (iterationId: string) => stopIteration(toValue(cohortId), iterationId),
    onSuccess: (_data, iid) => {
      const id = toValue(cohortId)
      qc.invalidateQueries({ queryKey: LAB_KEYS.iterations(id) })
      qc.invalidateQueries({ queryKey: LAB_KEYS.cohort(id) })
      qc.invalidateQueries({ queryKey: LAB_KEYS.runner })
      qc.invalidateQueries({ queryKey: LAB_KEYS.iterationProgress(id, iid) })
    },
  })
}

export function useCreateIterationMutation(cohortId: MaybeRefOrGetter<string>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: IterationCreatePayload) => createIteration(toValue(cohortId), payload),
    onSuccess: () => {
      const id = toValue(cohortId)
      // Auto-freeze may have flipped status; refresh everything that
      // surfaces it.
      qc.invalidateQueries({ queryKey: LAB_KEYS.cohort(id) })
      qc.invalidateQueries({ queryKey: LAB_KEYS.iterations(id) })
      qc.invalidateQueries({ queryKey: LAB_KEYS.trajectory(id) })
      qc.invalidateQueries({ queryKey: ['lab', 'cohorts'] })
    },
  })
}

export function useUpdateIterationMutation(
  cohortId: MaybeRefOrGetter<string>,
  iterationId: MaybeRefOrGetter<string>,
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (patch: {
      notes?: string | null
      verdict_override?: string | null
      recipe_id?: string | null
      variant_count?: number | null
    }) => updateIteration(toValue(cohortId), toValue(iterationId), patch),
    onSuccess: () => {
      const cid = toValue(cohortId)
      const iid = toValue(iterationId)
      qc.invalidateQueries({ queryKey: LAB_KEYS.iterations(cid) })
      // Recipe/variant_count changes wipe baked augmentations server-side —
      // refresh the gallery query too so the user sees the cleared state.
      qc.invalidateQueries({ queryKey: LAB_KEYS.augmentations(cid, iid) })
      qc.invalidateQueries({ queryKey: LAB_KEYS.iterationProgress(cid, iid) })
    },
  })
}

export function useLaunchTrainingMutation(
  cohortId: MaybeRefOrGetter<string>,
  iterationId: MaybeRefOrGetter<string>,
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => launchIterationTraining(toValue(cohortId), toValue(iterationId)),
    onSuccess: () => {
      const id = toValue(cohortId)
      const iid = toValue(iterationId)
      qc.invalidateQueries({ queryKey: LAB_KEYS.iterations(id) })
      qc.invalidateQueries({ queryKey: LAB_KEYS.cohort(id) })
      qc.invalidateQueries({ queryKey: LAB_KEYS.runner })
      qc.invalidateQueries({ queryKey: LAB_KEYS.iterationProgress(id, iid) })
    },
  })
}

export function useLaunchBenchmarkMutation(
  cohortId: MaybeRefOrGetter<string>,
  iterationId: MaybeRefOrGetter<string>,
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => launchIterationBenchmark(toValue(cohortId), toValue(iterationId)),
    onSuccess: () => {
      const id = toValue(cohortId)
      const iid = toValue(iterationId)
      qc.invalidateQueries({ queryKey: LAB_KEYS.iterations(id) })
      qc.invalidateQueries({ queryKey: LAB_KEYS.cohort(id) })
      qc.invalidateQueries({ queryKey: LAB_KEYS.runner })
      qc.invalidateQueries({ queryKey: LAB_KEYS.iterationProgress(id, iid) })
    },
  })
}

// ─── Live tests (Sprint 4) ──────────────────────────────────────────────

export function useLiveTestsQuery(
  cohortId: MaybeRefOrGetter<string>,
  iterationId: MaybeRefOrGetter<string | null | undefined>,
) {
  return useQuery({
    queryKey: computed(() =>
      LAB_KEYS.liveTests(toValue(cohortId), toValue(iterationId) ?? ''),
    ),
    queryFn: () =>
      fetchLiveTests(toValue(cohortId), toValue(iterationId) as string),
    enabled: computed(() => !!toValue(cohortId) && !!toValue(iterationId)),
    // 5 min — the sync mutation invalidates explicitly, so the staleTime
    // is just there to keep tab-switches snappy.
    staleTime: 5 * 60 * 1000,
  })
}

export function useSyncLiveTestsMutation(
  cohortId: MaybeRefOrGetter<string>,
  iterationId: MaybeRefOrGetter<string>,
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => syncLiveTests(toValue(iterationId)),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: LAB_KEYS.liveTests(toValue(cohortId), toValue(iterationId)),
      })
    },
  })
}

// ─── Dashboard + GC (Sprint 5) ──────────────────────────────────────────

export function useDashboardQuery() {
  return useQuery({
    queryKey: LAB_KEYS.dashboard,
    queryFn: () => fetchDashboard(),
    // Cross-cohort aggregations only change when iterations finish or
    // live-tests sync. Keep stale-while-revalidate semantics with 30s
    // freshness — cheap to recompute backend-side.
    staleTime: 30 * 1000,
  })
}

export function usePurgeAugmentationsMutation(
  cohortId: MaybeRefOrGetter<string>,
  iterationId: MaybeRefOrGetter<string>,
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      purgeIterationAugmentations(toValue(cohortId), toValue(iterationId)),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: LAB_KEYS.augmentations(toValue(cohortId), toValue(iterationId)),
      })
      qc.invalidateQueries({ queryKey: LAB_KEYS.dashboard })
    },
  })
}

export function usePurgeTestBundleMutation(
  cohortId: MaybeRefOrGetter<string>,
  iterationId: MaybeRefOrGetter<string>,
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      purgeIterationTestBundle(toValue(cohortId), toValue(iterationId)),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: LAB_KEYS.buildInfo(toValue(cohortId), toValue(iterationId)),
      })
    },
  })
}
