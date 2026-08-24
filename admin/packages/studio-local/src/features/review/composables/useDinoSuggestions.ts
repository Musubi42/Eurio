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
import { eurioApi, EurioApiError } from '@/shared/api/eurio-api'
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
  /** Non-null : un recadrage a rendu cette prédiction suspecte (migration 0013).
   *  Elle reste servie — un ajustement au micro ne la change presque jamais, et
   *  le reviewer recadre AVANT de choisir la pièce. On le DIT, on ne la cache
   *  pas : la cacher lui retirait son aide juste au moment où elle sert. */
  stale_since?: string | null
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

/**
 * Lit les suggestions sur `eurio-api` — le canonique, pas le ML local.
 *
 * Ce `fetch` visait `ML_API` (`127.0.0.1:8042`), en clair et sans auth. Hors de la
 * machine qui héberge le ML, il échouait par le réseau, `TypeError` renvoyait
 * `null`, et le panneau affichait « Pas de prédiction Dino pour ce crop · hors
 * scope ou pas encore backfillé » — un message qui accuse la BASE alors que le
 * coupable était l'ADRESSE. Observé le 2026-08-23 sur un crop dont l'API avait
 * bel et bien la prédiction (review-collaborative-v2, lot 6a).
 *
 * Côté serveur, `/review-queue/{…}/dino-suggestions` est désormais servi en
 * LECTURE PURE par l'image lean : 404 si la prédiction manque, jamais d'encodage
 * à la demande. Le `null` reste donc le contrat — Dino est une aide, pas un
 * prérequis pour reviewer.
 */
async function fetchOrNull(path: string): Promise<DinoSuggestionsResponse | null> {
  try {
    const body = await eurioApi.get<DinoSuggestionsResponse>(path)
    // `obverse_url` relative (`/referential/canonical/…`) → résolue contre l'API
    // qui a produit la réponse, PAS contre `ML_API` (même correctif qu'au lot 1).
    const promoteUrl = (s: DinoSuggestion): DinoSuggestion => ({
      ...s,
      obverse_url: s.obverse_url
        ? s.obverse_url.startsWith('http')
          ? s.obverse_url
          : `${eurioApi.base}${s.obverse_url}`
        : null,
    })
    return {
      ...body,
      top_k: (body.top_k ?? []).map(promoteUrl),
      top_k_country: (body.top_k_country ?? []).map(promoteUrl),
    }
  } catch (err) {
    if (err instanceof EurioApiError) {
      if (err.status === 404) return null // pas de prédiction pour ce crop
      console.warn(`[dino-suggestions] HTTP ${err.status} pour ${path}`)
      return null
    }
    if (err instanceof TypeError) return null // réseau coupé
    console.warn('[dino-suggestions] error', err)
    return null
  }
}

// Kind par défaut = banque large commémo + courantes (suggestions review).
//
// ⛔ Le repli vers `2eur_commemo` sur 404 a été RETIRÉ le 2026-08-24.
//
// Il paraissait prudent : « si la banque large n'est pas bâtie, retente sur
// l'ancienne ». En pratique il faisait la pire chose possible — servir des
// scores calculés par un AUTRE encodeur (vits14 contre vitl14), dont les
// similarités ne sont pas sur la même échelle, dans un panneau où le reviewer
// les compare à des seuils calibrés sur la première. Deux crops voisins
// pouvaient ainsi être jugés sur deux banques, et rien à l'écran ne disait
// laquelle. Depuis la bascule du verdict, ce serait en plus une liste et une
// pastille en désaccord par construction.
//
// Un 404 signifie « pas de prédiction pour ce crop », et le panneau sait déjà
// l'afficher. C'est la même leçon que les trois pannes du chantier pêche : un
// échec qui élargit ou qui invente est pire qu'un échec qui s'arrête.
const DEFAULT_ANCHORS_KIND = '2eur_all'

async function fetchWithKind(
  pathFor: (kind: string) => string,
  anchorsKind?: string,
): Promise<DinoSuggestionsResponse | null> {
  return fetchOrNull(pathFor(anchorsKind ?? DEFAULT_ANCHORS_KIND))
}

export async function fetchDinoSuggestionsByReviewId(
  reviewId: string,
  opts: { anchorsKind?: string } = {},
): Promise<DinoSuggestionsResponse | null> {
  return fetchWithKind(
    (kind) =>
      `/review-queue/${encodeURIComponent(reviewId)}/dino-suggestions?anchors_kind=${kind}`,
    opts.anchorsKind,
  )
}

export async function fetchDinoSuggestionsByAssetId(
  assetId: string,
  opts: { anchorsKind?: string } = {},
): Promise<DinoSuggestionsResponse | null> {
  return fetchWithKind(
    (kind) =>
      `/review-queue/asset/${encodeURIComponent(assetId)}/dino-suggestions?anchors_kind=${kind}`,
    opts.anchorsKind,
  )
}

/** Force un recalcul Dino (POST) sur un crop puis renvoie la réponse fraîche.
 *  Contrairement au GET, ce POST ENCODE le crop (torch) : il reste donc sur le
 *  ML LOCAL et n'existe pas sur le VPS. Le bouton qui l'appelle est dans une vue
 *  `heavy`, grisée en hébergé. Même banque que les lectures. */
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
  const kind = opts.anchorsKind ?? DEFAULT_ANCHORS_KIND
  // Pas de repli de banque ici non plus — recalculer sur une AUTRE banque que
  // celle affichée serait encore moins lisible que sur une lecture : le
  // reviewer vient d'appuyer sur un bouton et attend un résultat comparable.
  return postOrNull(
    `/review-queue/asset/${encodeURIComponent(assetId)}`
    + `/dino-suggestions/recompute?anchors_kind=${kind}`,
  )
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
