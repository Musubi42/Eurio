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
  cloneCohort,
  createIteration,
  fetchCohort,
  fetchCohortCaptures,
  fetchCohorts,
  fetchIterations,
  fetchRunnerStatus,
  fetchSensitivity,
  fetchTrajectory,
  generateCohortCsv,
  removeCoinFromCohort,
  syncCohortCaptures,
} from './useLabApi'
import type {
  CohortStatus,
  IterationCreatePayload,
} from '../types'

export const LAB_KEYS = {
  cohorts: (filters: { zone?: string | null; status?: CohortStatus | null } = {}) =>
    ['lab', 'cohorts', filters] as const,
  cohort: (id: string) => ['lab', 'cohort', id] as const,
  iterations: (cohortId: string) => ['lab', 'cohort', cohortId, 'iterations'] as const,
  trajectory: (cohortId: string) => ['lab', 'cohort', cohortId, 'trajectory'] as const,
  sensitivity: (cohortId: string) => ['lab', 'cohort', cohortId, 'sensitivity'] as const,
  captures: (cohortId: string) => ['lab', 'cohort', cohortId, 'captures'] as const,
  runner: ['lab', 'runner'] as const,
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

export function useRunnerStatusQuery() {
  return useQuery({
    queryKey: LAB_KEYS.runner,
    queryFn: () => fetchRunnerStatus(),
    refetchInterval: 5000,
    staleTime: 0,
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
      qc.invalidateQueries({ queryKey: ['lab', 'cohorts'] })
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
      qc.invalidateQueries({ queryKey: LAB_KEYS.captures(toValue(cohortId)) })
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
