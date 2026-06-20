// Composable pour /source-runs/:run_id/searches.
//
// Backend : ml/serving/sources/router.py → get_run_searches.

import { eurioApi, EurioApiError } from '@/shared/api/eurio-api'
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
  // Funnel ventilé.
  n_summaries: number | null
  n_after_groups: number | null
  n_raw_results: number | null
  n_kept_results: number | null
  duration_ms: number | null
  error: string | null
  // Marketplace ciblé par la search.
  marketplace: string | null
  // URL d'appel Browse rejouable.
  browse_url: string | null
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
  _sourceId: SourceId,
  runId: string,
  eurio_id?: string | null,
): Promise<RunSearches> {
  const qs = eurio_id ? `?eurio_id=${encodeURIComponent(eurio_id)}` : ''
  try {
    return await eurioApi.get<RunSearches>(`/source-runs/${runId}/searches${qs}`)
  } catch (err) {
    if (err instanceof EurioApiError) {
      throw new RunSearchesError(err.status, err.message)
    }
    throw err
  }
}
