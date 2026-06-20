// Composable pour /source-runs/:run_id/funnel.
//
// Backend : ml/serving/sources/router.py → get_run_funnel. Vue entonnoir
// d'un run (steps du pipeline + discovery → détection → review +
// rejets), pour l'onglet « Logs » de la page run-detail.

import { eurioApi, EurioApiError } from '@/shared/api/eurio-api'
import type { SourceId } from './useSourcesApi'

export type StepStatus = 'done' | 'running' | 'pending' | 'failed'

export interface FunnelStep {
  name: string // id PIPELINE_STEPS (discover, persist, …)
  status: StepStatus
}

export interface DiscardReason {
  reason: string
  count: number
}

export interface RunFunnel {
  run_id: string
  source_id: SourceId
  status: 'success' | 'partial' | 'failed' | 'running'
  current_step: string | null
  duration_s: number | null
  n_errors: number
  error_summary: string | null
  steps: FunnelStep[]
  // Discovery
  n_searches: number
  n_summaries: number
  n_after_groups: number
  n_kept: number
  // Détection (crop)
  n_images: number
  n_cropped: number
  n_zero_crops: number
  n_crop_pending: number
  // Rejets pré-ingestion
  n_discarded: number
  discards: DiscardReason[]
  // Sortie
  n_review_enqueued: number
  n_pending_quotes: number
  n_quotes: number
}

export class RunFunnelError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'RunFunnelError'
  }
}

// `sourceId` reste dans la signature pour stabilité d'appel — le run_id est
// globalement unique côté backend (Phase 2b), pas besoin de le scoper.
export async function fetchRunFunnel(
  _sourceId: SourceId,
  runId: string,
): Promise<RunFunnel> {
  try {
    return await eurioApi.get<RunFunnel>(`/source-runs/${runId}/funnel`)
  } catch (err) {
    if (err instanceof EurioApiError) {
      throw new RunFunnelError(err.status, err.message)
    }
    throw err
  }
}
