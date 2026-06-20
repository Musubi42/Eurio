// Composable pour /source-runs/:run_id/discarded.
//
// Backend : ml/serving/sources/router.py → get_run_discarded.
// Expose les listings rejetés pré-ingestion (accept_listing + theme_mismatch).

import { eurioApi, EurioApiError } from '@/shared/api/eurio-api'
import type { SourceId } from './useSourcesApi'

export interface DiscardedListing {
  id: string
  source_ref: string
  target_eurio_id: string | null
  reason: string
  title: string | null
  item_id: string | null
  item_web_url: string | null
  price: number | null
  currency: string | null
  raw_payload: Record<string, unknown> | null
  created_at: string
}

export interface DiscardedReasonGroup {
  reason: string
  count: number
}

export interface RunDiscarded {
  run_id: string
  source_id: SourceId
  total: number
  by_reason: DiscardedReasonGroup[]
  listings: DiscardedListing[]
}

export class RunDiscardedError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'RunDiscardedError'
  }
}

export async function fetchRunDiscarded(
  _sourceId: SourceId,
  runId: string,
  opts?: { eurio_id?: string | null; reason?: string | null },
): Promise<RunDiscarded> {
  const params = new URLSearchParams()
  if (opts?.eurio_id) params.set('eurio_id', opts.eurio_id)
  if (opts?.reason) params.set('reason', opts.reason)
  const qs = params.size ? `?${params.toString()}` : ''
  try {
    return await eurioApi.get<RunDiscarded>(`/source-runs/${runId}/discarded${qs}`)
  } catch (err) {
    if (err instanceof EurioApiError) {
      throw new RunDiscardedError(err.status, err.message)
    }
    throw err
  }
}

// Tone par raison (cohérent avec le panel Discovery searches).
// `theme_mismatch` et `text_contradict_*` sont des drops "souples" (le
// listing pourrait être ré-attribué à un autre eurio_id via une autre
// query), les autres sont des rejets "durs" (hors-scope).
export const REASON_TONE: Record<string, string> = {
  noise_title: 'var(--danger)',
  year_mismatch: 'var(--warning)',
  theme_mismatch: 'var(--gold-600)',
  non_eur: 'var(--ink-500)',
  no_price: 'var(--ink-500)',
  below_face: 'var(--warning)',
  above_extreme: 'var(--warning)',
  text_contradict_country: 'var(--gold-600)',
  text_contradict_year: 'var(--gold-600)',
  text_contradict_denomination: 'var(--gold-600)',
}

export function reasonTone(reason: string): string {
  return REASON_TONE[reason] || 'var(--ink-500)'
}

export const REASON_LABEL: Record<string, string> = {
  noise_title: 'Titre hors-scope (proof, métaux précieux, fautée…)',
  year_mismatch: 'Millésime du titre ≠ année de la pièce',
  theme_mismatch: 'Aucun token thème dans le titre (cas ambigu)',
  non_eur: 'Devise ≠ EUR',
  no_price: 'Pas de prix renseigné',
  below_face: 'Prix < 0.8 × face value',
  above_extreme: 'Prix > 500 × face value',
  text_contradict_country: 'Pays du titre ≠ pays du target',
  text_contradict_year: 'Année du titre ≠ année du target',
  text_contradict_denomination: 'Dénomination du titre ≠ celle du target',
}

export function reasonLabel(reason: string): string {
  return REASON_LABEL[reason] || reason
}
