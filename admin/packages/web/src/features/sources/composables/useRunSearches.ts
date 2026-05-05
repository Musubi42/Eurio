// Composable pour /sources/:id/runs/:run_id/searches.
//
// Backend : ml/api/sources_routes.py → get_run_searches.
// Doc : docs/sources-refacto/listing-debug-view-kickoff.md.

import { ML_API } from '@/features/training/composables/useTrainingApi'
import type { SourceId } from './useSourcesApi'

export type DiscoverySearchStatus = 'success' | 'empty' | 'failed'

export interface DiscoverySearchItem {
  id: string
  target_eurio_id: string | null
  endpoint: string | null
  query_q: string | null
  query_filters: Record<string, unknown> | null
  status: DiscoverySearchStatus
  http_status: number | null
  // Funnel ventilé (chunk 0 auto-validation).
  // n_summaries → n_after_groups → n_raw_results → n_kept_results.
  n_summaries: number | null
  n_after_groups: number | null
  n_raw_results: number | null
  n_kept_results: number | null
  duration_ms: number | null
  error: string | null
  created_at: string
}

export interface RunSearches {
  run_id: string
  source_id: SourceId
  searches: DiscoverySearchItem[]
}

export class RunSearchesError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'RunSearchesError'
  }
}

export async function fetchRunSearches(
  sourceId: SourceId,
  runId: string,
  eurio_id?: string | null,
): Promise<RunSearches> {
  const url = new URL(`${ML_API}/sources/${sourceId}/runs/${runId}/searches`)
  if (eurio_id) url.searchParams.set('eurio_id', eurio_id)
  const resp = await fetch(url.toString())
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      const body = await resp.json()
      if (body && typeof body === 'object' && 'detail' in body) {
        detail = String((body as { detail: unknown }).detail)
      }
    } catch {
      // ignore
    }
    throw new RunSearchesError(resp.status, detail)
  }
  return resp.json() as Promise<RunSearches>
}
