// Text signals composable — wraps the chunk 5+6 API
// (ml/api/review_queue_routes.py).
//
//   GET /review-queue/{review_id}/text-signals     (lookup by review_queue.id)
//   GET /review-queue/asset/{asset_id}/text-signals  (lookup by image_asset.id)
//
// Le signal vit au niveau du listing (= source_image), pas du crop —
// plusieurs assets d'un même listing partagent la même réponse.
//
// 404 = step `text_signal` n'a pas tourné sur ce source_image (run
// pré-chunk-5, ou hors scope). Le panel doit dégrader silencieusement
// — le texte est une couche d'aide, pas requis pour reviewer.

import { ML_API } from '@/features/training/composables/useTrainingApi'

export type VsTargetVerdict = 'convergent' | 'partial' | 'absent' | 'contradict'

export interface TextSignalsResponse {
  source_image_id: string
  extractor_version: string
  listing_title: string | null
  target_eurio_id: string | null
  countries: string[]            // ISO2 uppercase ("AD", "FR", ...)
  years: number[]
  denominations: number[]
  theme_tokens: string[]
  rejected_markers: string[]     // ['proof', 'metal', ...]
  is_lot: boolean
  coverage: 'rich' | 'sparse' | 'empty'
  matched: Record<string, string[]>
  vs_target_verdict: VsTargetVerdict | null
  contradictions: string[]       // ['country', 'year', 'denomination']
  convergences: string[]
  computed_at: string | null
}

async function fetchOrNull(path: string): Promise<TextSignalsResponse | null> {
  try {
    const resp = await fetch(`${ML_API}${path}`)
    if (resp.status === 404) return null
    if (!resp.ok) {
      console.warn(`[text-signals] HTTP ${resp.status} for ${path}`)
      return null
    }
    return (await resp.json()) as TextSignalsResponse
  } catch (err) {
    if (err instanceof TypeError) return null // network down
    console.warn('[text-signals] error', err)
    return null
  }
}

export async function fetchTextSignalsByReviewId(
  reviewId: string,
): Promise<TextSignalsResponse | null> {
  return fetchOrNull(`/review-queue/${encodeURIComponent(reviewId)}/text-signals`)
}

export async function fetchTextSignalsByAssetId(
  assetId: string,
): Promise<TextSignalsResponse | null> {
  return fetchOrNull(`/review-queue/asset/${encodeURIComponent(assetId)}/text-signals`)
}

// ─── Visual helpers ─────────────────────────────────────────────────────

export type VerdictTone = 'success' | 'warning' | 'neutral' | 'danger'

/** Map verdict → tone for chip + axis status colors. */
export function verdictTone(verdict: VsTargetVerdict | null): VerdictTone {
  switch (verdict) {
    case 'convergent':
      return 'success'
    case 'partial':
      return 'warning'
    case 'contradict':
      return 'danger'
    case 'absent':
    case null:
    default:
      return 'neutral'
  }
}

export function verdictColor(tone: VerdictTone): string {
  switch (tone) {
    case 'success':
      return 'var(--success)'
    case 'warning':
      return 'var(--gold-600)'
    case 'danger':
      return 'var(--danger)'
    case 'neutral':
      return 'var(--ink-400)'
  }
}

export function verdictLabel(verdict: VsTargetVerdict | null): string {
  switch (verdict) {
    case 'convergent':
      return 'convergent'
    case 'partial':
      return 'partial'
    case 'absent':
      return 'absent'
    case 'contradict':
      return 'contradict'
    default:
      return 'n/a'
  }
}

export type AxisName = 'country' | 'year' | 'denomination'
export type AxisState = 'convergent' | 'contradict' | 'absent'

/** Recompute per-axis state from the response — cohérent avec
 * ml/sources/text_signals/comparator.py::_country_axis / _year_axis /
 * _denomination_axis. Permet d'afficher ✓/✗/⊘ par axe sans appel
 * supplémentaire. */
export function axisState(
  signals: TextSignalsResponse,
  axis: AxisName,
): AxisState {
  if (signals.contradictions.includes(axis)) return 'contradict'
  if (signals.convergences.includes(axis)) return 'convergent'
  return 'absent'
}

export function axisStateColor(state: AxisState): string {
  switch (state) {
    case 'convergent':
      return 'var(--success)'
    case 'contradict':
      return 'var(--danger)'
    case 'absent':
      return 'var(--ink-400)'
  }
}

/** Icon glyph per axis state — kept as text for terminal-aesthetic
 * parity (cf. existing CandidateRow.vue / DinoSuggestions.vue). */
export function axisStateGlyph(state: AxisState): string {
  switch (state) {
    case 'convergent':
      return '✓'
    case 'contradict':
      return '✗'
    case 'absent':
      return '⊘'
  }
}
