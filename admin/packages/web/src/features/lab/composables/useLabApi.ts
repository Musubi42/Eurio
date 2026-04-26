// Fetch wrappers for the /lab/* subsystem served by the local ML API.
//
// Same host as the training composable (http://localhost:8042).

import { ML_API } from '@/features/training/composables/useTrainingApi'
import type {
  CohortCreatePayload,
  CohortSummary,
  IterationCreatePayload,
  IterationDetail,
  RunnerStatus,
  SensitivityEntry,
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

export async function fetchCohorts(zone?: string | null): Promise<CohortSummary[]> {
  const qs = zone ? `?zone=${encodeURIComponent(zone)}` : ''
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
  patch: { notes?: string | null; verdict_override?: string | null },
): Promise<IterationDetail> {
  return json<IterationDetail>(
    `/lab/cohorts/${encodeURIComponent(cohortId)}/iterations/${encodeURIComponent(iterationId)}`,
    { method: 'PUT', body: JSON.stringify(patch) },
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
