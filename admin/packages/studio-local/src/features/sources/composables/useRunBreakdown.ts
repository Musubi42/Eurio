// Composable pour /source-runs/:run_id/breakdown.
//
// Backend : ml/serving/sources/router.py → get_run_breakdown.

import { eurioApi, EurioApiError } from '@/shared/api/eurio-api'
import type { SourceId } from './useSourcesApi'

export interface RunBreakdownEntry {
  eurio_id: string
  was_targeted: boolean
  // Search axis (si.target_eurio_id = E)
  n_listings: number
  n_crops_searched: number
  n_searched_auto: number
  n_searched_review_single: number
  n_searched_review_lot: number
  n_searched_pending: number
  n_searched_rejected: number
  // Attribution axis (ia.eurio_id = E AND si.target_eurio_id != E)
  n_attributed_from_other: number
  via_lot: boolean
  // Output
  n_quotes: number
  // Marketplaces ayant produit ≥1 listing pour cet eurio_id (B4 multi-mkt).
  // Vide pour les runs pré-bascule (source_images.marketplace NULL).
  marketplaces: string[]
}

export interface RunBreakdown {
  run_id: string
  source_id: SourceId
  started_at: string
  status: 'success' | 'partial' | 'failed' | 'running'
  filters: Record<string, unknown>
  per_eurio: RunBreakdownEntry[]
}

export class RunBreakdownError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'RunBreakdownError'
  }
}

export async function fetchRunBreakdown(
  _sourceId: SourceId,
  runId: string,
): Promise<RunBreakdown> {
  try {
    return await eurioApi.get<RunBreakdown>(`/source-runs/${runId}/breakdown`)
  } catch (err) {
    if (err instanceof EurioApiError) {
      throw new RunBreakdownError(err.status, err.message)
    }
    throw err
  }
}
