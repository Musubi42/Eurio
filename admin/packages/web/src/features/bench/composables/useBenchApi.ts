// Composable — studio bench du theme-matcher eBay.
//
// Backend : ml/api/bench_routes.py → GET /bench/theme-match. Rejoue le
// gold gelé (196 listings) à travers le pipeline et renvoie, par
// listing, le label humain + les sorties étape par étape, plus les
// métriques agrégées et le contexte des groupes (sœurs).
//
// Local-only : dégrade proprement si le backend ML est éteint.

import { ML_API } from '@/features/training/composables/useTrainingApi'

export interface BenchMetrics {
  total: number
  n_valid: number
  n_false_discard: number
  false_discard_rate: number | null
  recall_rate: number | null
  n_auto_correct: number
  auto_attribution_rate: number | null
  n_kept_review: number
  review_rate: number | null
  n_auto_total: number
  precision: number | null
  n_auto_wrong: number
  n_junk: number
  n_correct_discard: number
  n_false_keep: number
  false_keep_rate: number | null
  lot_outcomes: Record<string, number>
  n_accept_rej: number
  n_matcher_rej: number
}

export interface BenchAccept {
  ok: boolean
  reason: string
}

export interface BenchMatcher {
  verdict: string // single | lot | ambiguous | no_match
  matched: string[]
  contradictions: string[]
}

export interface BenchListing {
  listing_id: string
  title: string
  marketplace: string | null
  group_year: number
  price: number | null
  currency: string | null
  bucket: string | null
  note: string | null
  verdict: string // label humain : coin:<eurio_id> | lot | not-a-coin | wrong-scope | ambiguous
  accept: BenchAccept
  matcher: BenchMatcher | null // null ssi accept a rejeté
  outcome: string // FALSE_DISCARD | auto_ok | auto_WRONG | review | junk_discarded | FALSE_KEEP | lot→…
  agreement: boolean
}

export interface BenchGroupCoin {
  eurio_id: string
  theme: string | null
  i18n: Record<string, string>
  aliases: string[]
}

export interface BenchReplay {
  metrics: BenchMetrics
  listings: BenchListing[]
  groups: Record<string, BenchGroupCoin[]>
}

export class BenchApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'BenchApiError'
  }
}

export async function fetchThemeMatchBench(): Promise<BenchReplay> {
  let resp: Response
  try {
    resp = await fetch(`${ML_API}/bench/theme-match`)
  } catch {
    throw new BenchApiError(0, 'Backend ML injoignable (lance `go-task ml:api`).')
  }
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
    throw new BenchApiError(resp.status, detail)
  }
  return resp.json() as Promise<BenchReplay>
}

// ── Présentation ───────────────────────────────────────────────────────────

// Tone d'une issue : rouge = désaccord (le pipeline s'est trompé vs le
// label humain), vert/neutre = accord.
export function outcomeTone(outcome: string): string {
  if (outcome.includes('WRONG') || outcome.includes('FALSE')) return 'var(--danger)'
  if (outcome === 'auto_ok') return 'var(--success)'
  if (outcome === 'junk_discarded') return 'var(--ink-500)'
  return 'var(--gold-600)' // review, lot→…
}

export const OUTCOME_LABEL: Record<string, string> = {
  FALSE_DISCARD: 'Faux rejet',
  auto_ok: 'Auto — correct',
  auto_WRONG: 'Auto — erronée',
  review: 'Review',
  junk_discarded: 'Junk rejeté',
  FALSE_KEEP: 'Junk gardé',
}

export function outcomeLabel(outcome: string): string {
  return OUTCOME_LABEL[outcome] ?? outcome
}

// Label humain → forme lisible.
export function verdictLabel(verdict: string): string {
  if (verdict.startsWith('coin:')) return verdict.slice(5)
  return verdict
}

export const ACCEPT_REASON_LABEL: Record<string, string> = {
  ok: 'accepté',
  noise_title: 'titre hors-scope',
  year_mismatch: 'millésime ≠ groupe',
  non_eur: 'devise ≠ EUR',
  no_price: 'pas de prix',
  below_face: 'prix < 0,8 × face',
  above_extreme: 'prix > 500 × face',
}

export function acceptReasonLabel(reason: string): string {
  return ACCEPT_REASON_LABEL[reason] ?? reason
}
