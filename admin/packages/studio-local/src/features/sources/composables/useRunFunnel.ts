// Composable pour /sources/:id/runs/:run_id/funnel.
//
// Backend : ml/api/sources_routes.py → get_run_funnel. Vue entonnoir
// d'un run (steps du pipeline + discovery → détection → review +
// rejets), pour l'onglet « Logs » de la page run-detail.

import { ML_API } from '@/features/training/composables/useTrainingApi'
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

export async function fetchRunFunnel(
  sourceId: SourceId,
  runId: string,
): Promise<RunFunnel> {
  const resp = await fetch(`${ML_API}/sources/${sourceId}/runs/${runId}/funnel`)
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
    throw new RunFunnelError(resp.status, detail)
  }
  return resp.json() as Promise<RunFunnel>
}
