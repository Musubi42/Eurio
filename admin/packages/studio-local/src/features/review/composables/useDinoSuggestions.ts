// Dino suggestions composable — wraps the auto-validation API.
//
// Endpoints (cf. ml/api/review_queue_routes.py + docs/sources-refacto/auto-validation/):
//   GET /review-queue/{review_id}/dino-suggestions     (lookup by review_queue.id)
//   GET /review-queue/asset/{asset_id}/dino-suggestions  (lookup by image_asset.id)
//
// The two endpoints return the same shape — the drawer single uses the
// review_id form, the drawer lot uses the asset_id form.
//
// 404 = asset is out of scope (e.g. not a 2€ commemorative, V1 scope) or
// auto_validate hasn't been backfilled yet for this crop. Callers
// should treat 404 as a soft "no suggestions available" state, not a
// hard error — Dino is an aid layer, not a blocker.

import { ML_API } from '@/features/training/composables/useTrainingApi'
import type {
  AutoValidateLevel,
  ConsensusLane,
  ConsensusOutcome,
  CriterionKey,
  CriterionState,
} from './useAutoValidateVerdict'

export interface DinoSuggestion {
  eurio_id: string
  sim: number
  country: string | null
  country_name: string | null
  year: number | null
  theme: string | null
  denomination: number | null
  is_commemorative: boolean | null
  obverse_url: string | null
}

export interface DinoSuggestionsResponse {
  asset_id: string
  encoder_version: string
  anchors_kind: string
  anchors_count: number
  computed_at: string | null
  duration_ms: number | null
  spread: number | null
  top1_eurio_id: string | null
  top1_sim: number | null
  top_k: DinoSuggestion[]
  // Country-restricted re-rank (chunk 3.5). Empty array when the crop has
  // no target country signal — front falls back to top_k only.
  target_country: string | null
  country_anchors_count: number | null
  country_spread: number | null
  top1_country_eurio_id: string | null
  top1_country_sim: number | null
  top_k_country: DinoSuggestion[]
  // eurio_id du target_eurio_id qui a piloté le scrape (parent
  // source_image). Sert au verdict d'auto-validation à comparer top1
  // vs target. Null sur sources legacy sans target.
  target_eurio_id: string | null
  // Seuils provisoires pour le verdict — source de vérité côté ML
  // (ml/foundation/thresholds.py), exposés ici pour que le front
  // n'ait pas à dupliquer de constantes.
  verdict_thresholds: {
    top1_country_sim_min: number
    country_spread_min: number
  }
  // Verdict d'auto-validation calculé côté serveur — source unique (C0 du
  // redesign auto-validation). Le front l'affiche tel quel (level/reason +
  // état par critère), il ne recalcule plus rien. null seulement si l'asset
  // est introuvable (ne devrait pas arriver : 404 amont si pas de prédiction).
  auto_validate_verdict: {
    level: AutoValidateLevel
    reason: string
    criteria: { key: CriterionKey; state: CriterionState }[]
  } | null
  // Verdict de CONSENSUS (C3) — la décision de routage qui fait foi (= la lane
  // posée en review_queue). Source du badge depuis le polish front : fin du
  // drift où le verdict Dino 4-niveaux pouvait diverger de la lane (ex.
  // crop_cap → Dino auto_candidate mais lane ccproxy). null seulement si
  // l'asset n'a aucun signal exploitable.
  consensus_verdict: {
    outcome: ConsensusOutcome
    lane: ConsensusLane
    reason: string
    rule: string
    confidence: number
  } | null
  // Abstention des suggestions (P5 dino-suggestions, calibrée audit Phase 0
  // sur le spread GLOBAL — la sim ne sépare pas le hors-scope) :
  // 'uncertain' = probablement hors banque ou design ambigu → le panel doit
  // le dire au lieu de présenter une liste classée trompeuse.
  abstention_state: AbstentionState
  abstention_thresholds: {
    spread_uncertain_max: number
    spread_confident_min: number
  }
  // Lot multi-pays suspecté (titre « diverse Länder / mixed / divers pays »).
  // Le pays cible du listing ne dit rien du pays de CHAQUE crop → le panel
  // montre le ranking global en premier, la bande pays en prior indicatif.
  multi_country_lot: boolean
}

export type AbstentionState = 'confident' | 'low_margin' | 'uncertain' | 'unknown'

/** Returns null if the API doesn't have suggestions yet (404) or is unreachable. */
async function fetchOrNull(path: string): Promise<DinoSuggestionsResponse | null> {
  try {
    const resp = await fetch(`${ML_API}${path}`)
    if (resp.status === 404) return null
    if (!resp.ok) {
      console.warn(`[dino-suggestions] HTTP ${resp.status} for ${path}`)
      return null
    }
    const body = (await resp.json()) as DinoSuggestionsResponse
    // Promote relative obverse_url paths to absolute (the FastAPI server
    // returns paths like "/images/<numista>/source").
    const promoteUrl = (s: DinoSuggestion): DinoSuggestion => ({
      ...s,
      obverse_url: s.obverse_url
        ? s.obverse_url.startsWith('http')
          ? s.obverse_url
          : `${ML_API}${s.obverse_url}`
        : null,
    })
    return {
      ...body,
      top_k: body.top_k.map(promoteUrl),
      top_k_country: (body.top_k_country ?? []).map(promoteUrl),
    }
  } catch (err) {
    if (err instanceof TypeError) return null // network down
    console.warn('[dino-suggestions] error', err)
    return null
  }
}

// Kind par défaut = banque large commémo + courantes (suggestions review).
// Fallback sur la banque historique 2eur_commemo si la banque 2eur_all n'est
// pas bâtie sur la machine qui sert l'API (404 propre → on retente).
const DEFAULT_ANCHORS_KIND = '2eur_all'
const FALLBACK_ANCHORS_KIND = '2eur_commemo'

async function fetchWithKindFallback(
  pathFor: (kind: string) => string,
  anchorsKind?: string,
): Promise<DinoSuggestionsResponse | null> {
  const kind = anchorsKind ?? DEFAULT_ANCHORS_KIND
  const first = await fetchOrNull(pathFor(kind))
  if (first || anchorsKind || kind === FALLBACK_ANCHORS_KIND) return first
  return fetchOrNull(pathFor(FALLBACK_ANCHORS_KIND))
}

export async function fetchDinoSuggestionsByReviewId(
  reviewId: string,
  opts: { anchorsKind?: string } = {},
): Promise<DinoSuggestionsResponse | null> {
  return fetchWithKindFallback(
    (kind) =>
      `/review-queue/${encodeURIComponent(reviewId)}/dino-suggestions?anchors_kind=${kind}`,
    opts.anchorsKind,
  )
}

export async function fetchDinoSuggestionsByAssetId(
  assetId: string,
  opts: { anchorsKind?: string } = {},
): Promise<DinoSuggestionsResponse | null> {
  return fetchWithKindFallback(
    (kind) =>
      `/review-queue/asset/${encodeURIComponent(assetId)}/dino-suggestions?anchors_kind=${kind}`,
    opts.anchorsKind,
  )
}

/** Force un recalcul Dino (POST) sur un crop puis renvoie la réponse fraîche.
 *  Contrairement au GET (qui ne calcule que si la prédiction manque), ce POST
 *  écrase une prédiction périmée. Même fallback de banque que les lectures. */
async function postOrNull(path: string): Promise<DinoSuggestionsResponse | null> {
  try {
    const resp = await fetch(`${ML_API}${path}`, { method: 'POST' })
    if (resp.status === 404) return null
    if (!resp.ok) {
      console.warn(`[dino-suggestions] recompute HTTP ${resp.status} for ${path}`)
      return null
    }
    return (await resp.json()) as DinoSuggestionsResponse
  } catch (err) {
    if (err instanceof TypeError) return null
    console.warn('[dino-suggestions] recompute error', err)
    return null
  }
}

export async function recomputeDinoSuggestionsByAssetId(
  assetId: string,
  opts: { anchorsKind?: string } = {},
): Promise<DinoSuggestionsResponse | null> {
  const pathFor = (kind: string) =>
    `/review-queue/asset/${encodeURIComponent(assetId)}/dino-suggestions/recompute?anchors_kind=${kind}`
  const kind = opts.anchorsKind ?? DEFAULT_ANCHORS_KIND
  const first = await postOrNull(pathFor(kind))
  if (first || opts.anchorsKind || kind === FALLBACK_ANCHORS_KIND) return first
  return postOrNull(pathFor(FALLBACK_ANCHORS_KIND))
}

// ─── Visual tier helpers ────────────────────────────────────────────────
//
// Dino sims are tassées sur euros (cf. memory feedback_dino_thresholds —
// p25=0.81 / p75=0.88 on the confusion map between obverses, even more
// compressed on scraped crops where p10..p90 = 0.56..0.83). Absolute
// thresholds drift hard; we use percentile-relative tiers within each
// response's own top_k to color-code only what stands out **for this
// query**, not for the whole catalog.

export type SimTier = 'top' | 'mid' | 'low'

/** Bucket a sim relative to the response's own top1 — only useful as visual
 * indication that one suggestion "stands out" within its top_k.
 * - top  : within 5% of top1 (winner zone)
 * - mid  : within 15% of top1
 * - low  : everything else
 */
export function simTier(sim: number, top1Sim: number): SimTier {
  if (top1Sim <= 0) return 'low'
  const ratio = sim / top1Sim
  if (ratio >= 0.95) return 'top'
  if (ratio >= 0.85) return 'mid'
  return 'low'
}

/** Map a tier to a token value (kept inline here so the consumer doesn't have
 * to know about colors — just pass the result to a CSS var or color prop). */
export function simTierColor(tier: SimTier): string {
  switch (tier) {
    case 'top':
      return 'var(--success)'
    case 'mid':
      return 'var(--gold-600)'
    case 'low':
      return 'var(--ink-400)'
  }
}

/** Quick label for spread interpretation — for the header chip in the panel. */
export function spreadLabel(spread: number | null): { text: string; tone: SimTier } {
  if (spread === null) return { text: '—', tone: 'low' }
  if (spread >= 0.05) return { text: 'net', tone: 'top' }
  if (spread >= 0.02) return { text: 'modéré', tone: 'mid' }
  return { text: 'tassé', tone: 'low' }
}

/** Label humain de l'état d'abstention (P5) — calculé côté serveur depuis le
 * spread global (seuils dans ml/training/foundation/thresholds.py). */
export function abstentionLabel(state: AbstentionState): { text: string; tone: SimTier } {
  switch (state) {
    case 'confident':
      return { text: 'confiant', tone: 'top' }
    case 'low_margin':
      return { text: 'faible marge', tone: 'mid' }
    case 'uncertain':
      return { text: 'incertain', tone: 'low' }
    case 'unknown':
      return { text: '—', tone: 'low' }
  }
}
