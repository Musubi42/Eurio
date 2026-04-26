// Fetch wrappers for the /benchmark/* subsystem served by the local ML API.
//
// Same host as the training composable (http://localhost:8042).

import { ML_API } from '@/features/training/composables/useTrainingApi'
import type {
  BenchmarkLibrary,
  BenchmarkPhotosResponse,
  BenchmarkRunDetail,
  BenchmarkRunsList,
  RunBenchmarkPayload,
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

export async function fetchLibrary(): Promise<BenchmarkLibrary> {
  return json<BenchmarkLibrary>('/benchmark/library')
}

export async function fetchBenchmarkRuns(params: {
  model_name?: string
  recipe_id?: string
  zone?: string
  limit?: number
  offset?: number
} = {}): Promise<BenchmarkRunsList> {
  const qs = new URLSearchParams()
  if (params.model_name) qs.set('model_name', params.model_name)
  if (params.recipe_id) qs.set('recipe_id', params.recipe_id)
  if (params.zone) qs.set('zone', params.zone)
  if (params.limit) qs.set('limit', String(params.limit))
  if (params.offset) qs.set('offset', String(params.offset))
  const q = qs.toString() ? `?${qs.toString()}` : ''
  return json<BenchmarkRunsList>(`/benchmark/runs${q}`)
}

export async function fetchBenchmarkRun(runId: string): Promise<BenchmarkRunDetail> {
  return json<BenchmarkRunDetail>(`/benchmark/runs/${encodeURIComponent(runId)}`)
}

export async function fetchBenchmarkPhotos(eurio_id: string): Promise<BenchmarkPhotosResponse> {
  return json<BenchmarkPhotosResponse>(`/benchmark/photos/${encodeURIComponent(eurio_id)}`)
}

export function thumbnailUrl(relativePath: string): string {
  return `${ML_API}/benchmark/photos/thumbnail/${relativePath}`
}

export async function postBenchmarkRun(payload: RunBenchmarkPayload): Promise<{ run_id: string; status: string }> {
  return json<{ run_id: string; status: string }>('/benchmark/run', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function deleteBenchmarkRun(runId: string): Promise<void> {
  await json<{ deleted: boolean }>(`/benchmark/runs/${encodeURIComponent(runId)}`, {
    method: 'DELETE',
  })
}
