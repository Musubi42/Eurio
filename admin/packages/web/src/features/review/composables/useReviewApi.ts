// Review queue API composable — backed by ml/api/review_queue_routes.py.
//
// Endpoints (cf. docs/sources-refacto/review-queue.md §"Endpoints API attendus") :
//   GET    /review-queue?status=open&limit=20&order=priority
//   GET    /review-queue/:id
//   POST   /review-queue/:id/decide
//   POST   /review-queue/:id/skip
//   POST   /review-queue/:id/reject
//   GET    /review-queue/stats
//
// Network-down fallback: returns the embedded MOCK_QUEUE so the page
// stays usable in pure-front dev (no FastAPI running). When a real
// backend with no review items returns an empty array, we surface the
// empty state truthfully (no mock substitution).

import { ML_API } from '@/features/training/composables/useTrainingApi'

export type ReviewFace = 'obverse' | 'reverse' | 'unknown'
export type ReviewSource = 'ebay' | 'catawiki' | 'mdp' | 'lmdlp' | 'numista'
// Chunk C4 — taxonomie listing + état numismatique (cf. C2).
export type ListingKind = 'single' | 'lot' | 'coffret' | 'graded_slab'
export type ConditionTier = 'UNC' | 'TTB' | 'TB'

/** Prix de référence agrégé (coin_market_quotes) pour un tier d'état. */
export interface MarketQuote {
  condition: string
  p10: number | null
  p50: number | null
  p90: number | null
  sample_size: number
  period_start: string
}

export interface ReviewCandidate {
  eurio_id: string
  score: number
  label: string
  country: string
  denomination: string
  year: number | null
  canonical_thumb_url: string
}

export interface ReviewItem {
  id: string
  crop_url: string
  bbox: { x: number; y: number; w: number; h: number } | null
  source: ReviewSource
  source_ref: string
  listing_title: string
  listing_url: string | null
  listing_price: number | null
  candidates: ReviewCandidate[]
  face_detected: ReviewFace | null
  priority: number
  is_multi_coin_lot: boolean
  quality_score: number
  enqueued_at: string
  // eurio_id qui a piloté le scrape (parent source_image). 80 % des
  // reviews sont la cible — le drawer la pré-sélectionne au top de la
  // colonne suggestions pour gagner en vélocité. Optionnels car les
  // mocks legacy + sources sans target les laissent à null.
  target_eurio_id?: string | null
  target_candidate?: ReviewCandidate | null
  // Chunk 5b — pièces du groupe de découverte (2 € commémo, même pays +
  // année). Non vide seulement quand le theme-match n'a pas tranché
  // (target_candidate null, verdict ambigu) : le reviewer choisit la
  // sœur d'un clic au lieu de passer par la recherche libre.
  group_candidates?: ReviewCandidate[]
  // Review « N-contre-designs » — design groups avers standard du pays pour
  // un crop issu d'un scrape standard (listing_year null). Affichés en
  // priorité tout en haut : le reviewer tranche entre N designs (ex. ES →
  // Juan Carlos t1/t2 / Felipe VI) d'un clic. eurio_id = membre représentant
  // (la décision écrit ce membre → classe = son design_group). Vide pour les
  // crops commémo (année présente).
  standard_candidates?: ReviewCandidate[]
  // Chunk Cr — top-1 DINOv2 inliné (dinov2-vits14, 2eur_commemo).
  // Préférence country-band > global. null si pas de prédiction Dino ou
  // eurio_id mort. Sert au bouton « Accept Dino (D) » 1-clic dans
  // SingleReviewView — face hardcodée obverse (ancres = obverses Numista).
  dino_top1?: ReviewCandidate | null
  // Chunk C4 — contexte listing pour la carte d'audit « Listing & marché ».
  // Issu de C1 (source_images) + C2 (listing_text_signals). Optionnels :
  // null sur les rows antérieures / les mocks.
  listing_kind?: ListingKind | null
  listing_kind_confidence?: number | null
  condition?: ConditionTier | null
  condition_confidence?: number | null
  listing_origin_date?: string | null
  sold_qty?: number | null
}

export interface ReviewDecision {
  eurio_id: string
  face: ReviewFace
  variant_kind?: string
  notes?: string
}

export interface ReviewStats {
  n_pending: number
  n_done_today: number
  median_seconds_per_decision: number
  n_done_this_week: number
}

// ─── Public API ─────────────────────────────────────────────────────────

/** Returns null on network error so callers can mock-fallback. */
async function safeFetch<T>(path: string, init?: RequestInit): Promise<T | null> {
  try {
    const resp = await fetch(`${ML_API}${path}`, init)
    if (!resp.ok) {
      // 4xx/5xx with a real backend: surface the error to the caller.
      const detail = await resp.json().catch(() => ({ detail: `HTTP ${resp.status}` }))
      throw new ReviewApiError(resp.status, typeof detail === 'object' && detail && 'detail' in detail
        ? String((detail as { detail: unknown }).detail)
        : `HTTP ${resp.status}`)
    }
    return (await resp.json()) as T
  } catch (err) {
    if (err instanceof TypeError) return null  // network down → fallback
    throw err
  }
}

export class ReviewApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message)
  }
}

function promoteUrl(url: string): string {
  if (!url) return url
  return url.startsWith('http') ? url : `${ML_API}${url}`
}

function promoteCandidateThumb(c: ReviewCandidate): ReviewCandidate {
  return { ...c, canonical_thumb_url: promoteUrl(c.canonical_thumb_url) }
}

function promoteItemUrls(r: ReviewItem): ReviewItem {
  return {
    ...r,
    crop_url: promoteUrl(r.crop_url),
    // Toutes les listes de candidats ont une vignette canonique (relative
    // /referential/… ou /images/… → préfixe ML_API requis). Avant, seuls
    // target_candidate et dino_top1 étaient promus → vignettes cassées dans
    // « candidats auto-name » et « pièces standards » à URL locale.
    candidates: r.candidates?.map(promoteCandidateThumb) ?? r.candidates,
    standard_candidates: r.standard_candidates?.map(promoteCandidateThumb),
    group_candidates: r.group_candidates?.map(promoteCandidateThumb),
    target_candidate: r.target_candidate
      ? promoteCandidateThumb(r.target_candidate)
      : r.target_candidate,
    dino_top1: r.dino_top1 ? promoteCandidateThumb(r.dino_top1) : r.dino_top1,
  }
}

export async function fetchReviewQueue(
  opts: {
    limit?: number
    cohortId?: string | null
    lane?: string | null
    eurioId?: string | null
    /** IDs review_queue explicites (galerie enrichment → review ciblée). */
    reviewIds?: string[] | null
  } = {},
): Promise<ReviewItem[]> {
  const limit = opts.limit ?? 30
  const params = new URLSearchParams({ limit: String(limit), order: 'priority' })
  if (opts.cohortId) params.set('cohort_id', opts.cohortId)
  if (opts.lane) params.set('lane', opts.lane)
  if (opts.eurioId) params.set('eurio_id', opts.eurioId)
  if (opts.reviewIds && opts.reviewIds.length) params.set('review_ids', opts.reviewIds.join(','))
  const real = await safeFetch<ReviewItem[]>(`/review-queue?${params.toString()}`)
  if (real !== null) {
    return real.map(promoteItemUrls)
  }

  await delay(120)
  return MOCK_QUEUE.slice(0, limit)
}

export async function fetchReviewItem(id: string): Promise<ReviewItem> {
  const real = await safeFetch<ReviewItem>(`/review-queue/${encodeURIComponent(id)}`)
  if (real !== null) {
    return promoteItemUrls(real)
  }

  await delay(60)
  const item = MOCK_QUEUE.find((r) => r.id === id)
  if (!item) throw new Error(`Review introuvable : ${id}`)
  return item
}

export async function fetchReviewStats(): Promise<ReviewStats> {
  const real = await safeFetch<ReviewStats>('/review-queue/stats')
  if (real !== null) return real

  await delay(60)
  return {
    n_pending: 1247,
    n_done_today: 47,
    median_seconds_per_decision: 8.3,
    n_done_this_week: 314,
  }
}

// `keepalive` permet au POST de survivre à un unload de page (fermeture
// d'onglet pendant la fenêtre d'undo). Cf. SingleReviewView — commit
// différé.
export interface CommitOpts {
  keepalive?: boolean
}

export async function decideReviewItem(
  id: string,
  payload: ReviewDecision,
  opts: CommitOpts = {},
): Promise<void> {
  const real = await safeFetch<unknown>(`/review-queue/${encodeURIComponent(id)}/decide`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    keepalive: opts.keepalive,
  })
  if (real === null) {
    await delay(40)
    console.info('[mock fallback] decide', id, payload)
  }
}

export async function skipReviewItem(id: string, opts: CommitOpts = {}): Promise<void> {
  const real = await safeFetch<unknown>(`/review-queue/${encodeURIComponent(id)}/skip`, {
    method: 'POST',
    keepalive: opts.keepalive,
  })
  if (real === null) {
    await delay(20)
    console.info('[mock fallback] skip', id)
  }
}

export async function rejectReviewItem(id: string, opts: CommitOpts = {}): Promise<void> {
  const real = await safeFetch<unknown>(`/review-queue/${encodeURIComponent(id)}/reject`, {
    method: 'POST',
    keepalive: opts.keepalive,
  })
  if (real === null) {
    await delay(20)
    console.info('[mock fallback] reject', id)
  }
}

/**
 * Corrige manuellement listing_kind et/ou condition d'un listing (C4).
 * Se propage à toutes les photos du listing côté backend. Fire-and-forget
 * côté appelant : un échec ne bloque pas le flow d'attribution.
 */
export async function correctListing(
  id: string,
  payload: { listing_kind?: ListingKind; condition?: ConditionTier },
): Promise<void> {
  const real = await safeFetch<unknown>(
    `/review-queue/${encodeURIComponent(id)}/correct-listing`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  if (real === null) {
    await delay(20)
    console.info('[mock fallback] correct-listing', id, payload)
  }
}

/**
 * Requalifie le crop courant — et tout son listing — en LOT (review_queue.kind
 * passe de 'single' à 'lot'). Les crops du listing quittent la queue single et
 * basculent dans le flow lot. Réservé au cas « ce single est en fait un lot ».
 */
export interface RequalifyLotResult {
  status: string
  listing_key: string
  n_requalified: number
  n_images: number
}

export async function requalifyReviewAsLot(id: string): Promise<RequalifyLotResult> {
  const real = await safeFetch<RequalifyLotResult>(
    `/review-queue/${encodeURIComponent(id)}/requalify-lot`,
    { method: 'POST' },
  )
  if (real === null) {
    throw new Error('Backend indisponible — la requalification en lot n’a pas pu être enregistrée.')
  }
  return real
}

// ─── Re-crop manuel (chantier crop-quality-overhaul, Session B) ──────────

/** Contexte de l'éditeur de cercle : le RAW (sur lequel on dessine) + le
 *  cercle de départ (crop actuel), en px NATIFS du raw. */
export interface CropEditContext {
  asset_id: string
  source: string
  raw_url: string
  crop_url: string
  raw_width: number | null
  raw_height: number | null
  hint: { cx: number; cy: number; r: number } | null
  // Cercle dominant détecté dans le raw (source mono-pièce) : point de départ
  // de l'éditeur quand le crop stocké est mal dimensionné. null sur les lots.
  suggested_circle?: { cx: number; cy: number; r: number } | null
}

export interface ManualCropResult {
  asset_id: string
  cx: number
  cy: number
  r: number
  bbox: { x: number; y: number; w: number; h: number }
  width: number
  height: number
  detection_method: string
  crop_b64: string
  minio_ok: boolean
}

/** Charge le raw + le cercle de départ pour l'éditeur. Pas de fallback mock :
 *  l'éditeur n'a de sens qu'avec un vrai backend (raw en cache local). */
export async function fetchCropEditContext(reviewId: string): Promise<CropEditContext> {
  const real = await safeFetch<CropEditContext>(
    `/review-queue/${encodeURIComponent(reviewId)}/crop-edit-context`,
  )
  if (real === null) {
    throw new Error('Backend indisponible — le crop manuel requiert l’API ML locale.')
  }
  return {
    ...real,
    raw_url: promoteUrl(real.raw_url),
    crop_url: promoteUrl(real.crop_url),
  }
}

/** Re-croppe l'asset depuis un cercle (cx,cy,r) en px natifs du raw. Écrase le
 *  crop (cache + MinIO + DB) au format prod ; eurio_id préservé, review inchangée. */
export async function manualCrop(
  reviewId: string,
  circle: { cx: number; cy: number; r: number },
): Promise<ManualCropResult> {
  const real = await safeFetch<ManualCropResult>(
    `/review-queue/${encodeURIComponent(reviewId)}/manual-crop`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(circle),
    },
  )
  if (real === null) {
    throw new Error('Backend indisponible — le re-crop manuel n’a pas pu être enregistré.')
  }
  return real
}

// ─── Re-crop manuel keyé ASSET (page coin-detail, hors review queue) ─────
// Même cœur backend que la voie review (crop_edit.py), mais l'éditeur s'ouvre
// sur une vignette de la galerie enrichment : recadrage EN PLACE, statut +
// eurio_id préservés (un recadrage ≠ une décision). Cf. coin_assets_routes.

/** Charge le raw + le cercle de départ pour l'éditeur, depuis un asset_id. */
export async function fetchAssetCropEditContext(assetId: string): Promise<CropEditContext> {
  const real = await safeFetch<CropEditContext>(
    `/coins/assets/${encodeURIComponent(assetId)}/crop-edit-context`,
  )
  if (real === null) {
    throw new Error('Backend indisponible — le crop manuel requiert l’API ML locale.')
  }
  return {
    ...real,
    raw_url: promoteUrl(real.raw_url),
    crop_url: promoteUrl(real.crop_url),
  }
}

/** Re-croppe un asset en place (écrase cache + MinIO + DB au format prod). */
export async function manualCropAsset(
  assetId: string,
  circle: { cx: number; cy: number; r: number },
): Promise<ManualCropResult> {
  const real = await safeFetch<ManualCropResult>(
    `/coins/assets/${encodeURIComponent(assetId)}/manual-crop`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(circle),
    },
  )
  if (real === null) {
    throw new Error('Backend indisponible — le re-crop manuel n’a pas pu être enregistré.')
  }
  return real
}

// ─── Claude vision (ccproxy) ─────────────────────────────────────────────

export type ClaudeVerdict = 'match' | 'no_match' | 'uncertain' | 'error'
export type ClaudeAction = 'ack' | 'reject'

export interface ClaudePendingItem {
  review_id: string
  image_asset_id: string
  crop_url: string
  listing_title: string
  listing_url: string | null
  source: string
  target_eurio_id: string
  target_label: string
  target_thumb_url: string | null
  verdict: ClaudeVerdict
  confidence: number | null
  face_detected: string | null
  model: string
  raw_content: string
  computed_at: string
}

export interface ClaudePendingResult {
  total_pending: number
  by_verdict: Record<string, number>
  items: ClaudePendingItem[]
}

export interface ClaudeBatchResult {
  processed: number
  judged: number
  skipped_already_judged: number
  skipped_no_canonical: number
  skipped_not_open?: number   // chunk C : items décidés par une autre voie
  by_verdict: Record<string, number>
  errors: number
  model: string
}

export interface ClaudeAckResult {
  requested: number
  committed: number
  rejected: number
  skipped: number
}

/** Liste les verdicts Claude en attente d'acquittement humain. */
export async function fetchClaudePendingAcks(
  opts: { verdict?: ClaudeVerdict; limit?: number; cohortId?: string | null } = {},
): Promise<ClaudePendingResult> {
  const verdict = opts.verdict ?? 'match'
  const limit = opts.limit ?? 200
  const cohortQs = opts.cohortId ? `&cohort_id=${encodeURIComponent(opts.cohortId)}` : ''
  const qs = `verdict=${verdict}&limit=${limit}${cohortQs}`
  const real = await safeFetch<ClaudePendingResult>(
    `/review-queue/claude/pending-acks?${qs}`,
  )
  if (real !== null) return real
  return { total_pending: 0, by_verdict: {}, items: [] }
}

/**
 * Lance un batch de jugement Claude sur la queue. Long : ~3-5 s par item
 * en Sonnet via ccproxy. Par défaut idempotent (skip les items déjà jugés).
 */
export async function runClaudeBatch(
  opts: {
    limit?: number
    scope?: Array<'partial' | 'divergent' | 'auto_candidate' | 'unknown'>
    model?: 'haiku' | 'sonnet' | 'opus'
    force?: boolean
    cohortId?: string | null
  } = {},
): Promise<ClaudeBatchResult> {
  const limit = opts.limit ?? 50
  const cohortQs = opts.cohortId ? `&cohort_id=${encodeURIComponent(opts.cohortId)}` : ''
  const qs = `limit=${limit}${cohortQs}`
  const body = {
    scope: opts.scope ?? ['partial', 'divergent'],
    model: opts.model ?? 'sonnet',
    force: opts.force ?? false,
  }
  const real = await safeFetch<ClaudeBatchResult>(
    `/review-queue/claude/batch?${qs}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  )
  if (real !== null) return real
  return {
    processed: 0, judged: 0, skipped_already_judged: 0,
    skipped_no_canonical: 0, by_verdict: {}, errors: 0,
    model: 'claude-sonnet-4-6',
  }
}

/**
 * Acquitte ou rejette une sélection de verdicts Claude. ``ack`` écrit la
 * décision finale dans review_queue (decided_by='claude_ack_human').
 * ``reject`` marque juste le verdict Claude comme rejeté (l'item reste
 * en queue manuelle classique).
 */
export async function ackClaudeVerdicts(
  reviewIds: string[],
  action: ClaudeAction,
): Promise<ClaudeAckResult> {
  const real = await safeFetch<ClaudeAckResult>(
    '/review-queue/claude/acknowledge',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ review_ids: reviewIds, action }),
    },
  )
  if (real !== null) return real
  return { requested: reviewIds.length, committed: 0, rejected: 0, skipped: 0 }
}

// ─── Dashboard triage stats ──────────────────────────────────────────────

export interface TriageVerdictCounts {
  auto_candidate: number
  partial: number
  divergent: number
  unknown: number
}

export interface TriageStats {
  n_pending: number
  n_done_today: number
  n_done_today_auto_dino: number
  n_done_this_week: number
  by_verdict: TriageVerdictCounts
  // WS1 : compteurs par LANE PERSISTÉE (review_queue.lane). Source de vérité des
  // 3 cartes du cockpit (manual/auto_accept/ccproxy). by_verdict reste fourni
  // pour compat/debug, mais l'affichage vient de by_lane.
  by_lane: { manual: number; auto_accept: number; ccproxy: number }
  // Lots (kind='lot') PAR LANE — décompose la carte « Lots » (B3 : on ne cache
  // plus les lots manuels). Optionnel : backends antérieurs au chunk F6.
  by_lane_lot?: { manual: number; auto_accept: number; ccproxy: number }
  // Crops en review LOT (kind='lot') — flow distinct du single (cockpit cohort).
  n_lot_crops: number
  // Crops rejetés (récupérables via /review/recover) + items skippés (report
  // informationnel). Optionnels : backends antérieurs au chunk recover.
  n_rejected?: number
  n_skipped?: number
}

/**
 * Agrégat unique pour le dashboard `/review` : compte total queue +
 * répartition par verdict d'auto-validation (auto_candidate / partial /
 * divergent / unknown). Source de vérité partagée avec `runAutoAccept`.
 *
 * `cohortId` (optionnel) restreint tous les compteurs aux images dont le coin
 * theme-matché est dans la cohort — alimente les 3 cartes de la page cohort.
 */
export async function fetchTriageStats(cohortId?: string | null): Promise<TriageStats> {
  const qs = cohortId ? `?cohort_id=${encodeURIComponent(cohortId)}` : ''
  const real = await safeFetch<TriageStats>(`/review-queue/triage-stats${qs}`)
  if (real !== null) return real
  // Mock fallback (backend off) — zéros honnêtes.
  return {
    n_pending: 0,
    n_done_today: 0,
    n_done_today_auto_dino: 0,
    n_done_this_week: 0,
    by_verdict: { auto_candidate: 0, partial: 0, divergent: 0, unknown: 0 },
    by_lane: { manual: 0, auto_accept: 0, ccproxy: 0 },
    by_lane_lot: { manual: 0, auto_accept: 0, ccproxy: 0 },
    n_lot_crops: 0,
    n_rejected: 0,
    n_skipped: 0,
  }
}

/**
 * Déplace un item de review vers la lane MANUELLE (switch unidirectionnel, WS1).
 * Sticky côté backend (lane_source='human') : aucun recalcul Dino ne le re-route.
 */
export async function moveReviewLaneToManual(id: string): Promise<void> {
  await safeFetch<unknown>(
    `/review-queue/${encodeURIComponent(id)}/move-lane`,
    { method: 'POST' },
  )
}

// ─── Récupération des crops rejetés (un-reject) ──────────────────────────

/** Un crop rejeté, récupérable via la grille /review/recover. */
export interface RejectedCrop {
  review_id: string
  image_asset_id: string
  crop_url: string
  listing_title: string | null
  quality_reason: string | null
  decided_at: string | null
  target_eurio_id: string | null
  target_label: string | null
}

export interface RestoreResult {
  restored: number
  skipped: string[]
}

/** Liste les crops rejetés d'une cohort (grille de récupération). */
export async function fetchRejectedCrops(
  cohortId?: string | null,
): Promise<RejectedCrop[]> {
  const qs = cohortId ? `?cohort_id=${encodeURIComponent(cohortId)}` : ''
  const real = await safeFetch<RejectedCrop[]>(`/review-queue/rejected${qs}`)
  if (real === null) return []
  return real.map((r) => ({ ...r, crop_url: promoteUrl(r.crop_url) }))
}

/** Ré-ouvre des reviews rejetées : elles repassent en queue manuelle. */
export async function restoreRejected(reviewIds: string[]): Promise<RestoreResult> {
  const real = await safeFetch<RestoreResult>('/review-queue/restore', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ review_ids: reviewIds }),
  })
  if (real === null) {
    throw new Error('Backend indisponible — la remise en queue n’a pas pu être enregistrée.')
  }
  return real
}

// ─── Auto-accept déterministe (Dino + texte, pas de Claude) ──────────────

export interface AutoAcceptPreviewItem {
  review_id: string
  image_asset_id: string
  crop_url: string
  listing_title: string
  listing_url: string | null
  source: string
  target_eurio_id: string
  target_label: string
  target_thumb_url: string | null
  sim: number | null
  spread: number | null
  face_detected: string | null
  reason: string
}

export interface AutoAcceptResult {
  processed: number
  accepted: number
  by_category: Record<string, number>
  dry_run: boolean
  preview: AutoAcceptPreviewItem[]
}

/**
 * Itère la queue open et auto-décide les items dont le verdict combiné
 * (Dino + texte) est `auto_candidate`. En `dry_run=true`, ne touche à
 * rien et retourne en plus la liste `preview[]` enrichie (crop, target
 * canonical, sim/spread, listing) pour l'écran de revue manuelle.
 *
 * En `dry_run=false` avec `reviewIds`, seuls les IDs fournis sont auto-
 * acceptés (re-validation du verdict côté serveur — un ID qui a glissé
 * hors `auto_candidate` est silencieusement skip).
 */
export async function runAutoAccept(
  opts: { limit?: number; dryRun?: boolean; reviewIds?: string[]; cohortId?: string | null } = {},
): Promise<AutoAcceptResult> {
  const limit = opts.limit ?? 2000
  const dryRun = opts.dryRun ?? false
  const cohortQs = opts.cohortId ? `&cohort_id=${encodeURIComponent(opts.cohortId)}` : ''
  const qs = `limit=${limit}&dry_run=${dryRun}${cohortQs}`
  const real = await safeFetch<AutoAcceptResult>(
    `/review-queue/auto-accept/run?${qs}`,
    {
      method: 'POST',
      headers: opts.reviewIds ? { 'Content-Type': 'application/json' } : undefined,
      body: opts.reviewIds ? JSON.stringify({ review_ids: opts.reviewIds }) : undefined,
    },
  )
  if (real !== null) return real
  // Mock fallback — backend off : retourne 0 partout, ne ment pas.
  return {
    processed: 0,
    accepted: 0,
    by_category: { auto_candidate: 0, partial: 0, divergent: 0, unknown: 0 },
    dry_run: dryRun,
    preview: [],
  }
}

/** Derniers prix de référence par pièce (un par tier d'état). C4. */
export async function fetchMarketQuotes(
  eurioIds: string[],
): Promise<Record<string, MarketQuote[]>> {
  if (eurioIds.length === 0) return {}
  const qs = encodeURIComponent(eurioIds.join(','))
  const real = await safeFetch<{ quotes: Record<string, MarketQuote[]> }>(
    `/sources/ebay/market-quotes?eurio_ids=${qs}`,
  )
  return real?.quotes ?? {}
}

// ─── Mock data ──────────────────────────────────────────────────────────

function delay(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

function thumb(seed: string, w = 224, h = 224): string {
  const palette = ['EDEDF5/1A1B4B', 'F5EBD3/8F7637', 'D8D9E8/0E0E1F', 'E2E0D6/55566C']
  const c = palette[seed.charCodeAt(0) % palette.length]
  return `https://placehold.co/${w}x${h}/${c}?text=${encodeURIComponent(seed)}`
}

const COUNTRY_LABEL: Record<string, string> = {
  BE: 'Belgique', FR: 'France', DE: 'Allemagne', IT: 'Italie', ES: 'Espagne',
  NL: 'Pays-Bas', LU: 'Luxembourg', IE: 'Irlande', PT: 'Portugal', FI: 'Finlande',
  GR: 'Grèce', AT: 'Autriche', CY: 'Chypre', MT: 'Malte', SK: 'Slovaquie',
  SI: 'Slovénie', EE: 'Estonie', LV: 'Lettonie', LT: 'Lituanie', HR: 'Croatie',
  BG: 'Bulgarie',
}

function makeCandidate(country: string, denom: string, year: number | null, score: number): ReviewCandidate {
  const id = `${country}-${denom.toLowerCase().replace(/\s/g, '')}-${year ?? 'na'}`
  return {
    eurio_id: id,
    score,
    label: `${COUNTRY_LABEL[country] ?? country} · ${denom}${year ? ` · ${year}` : ''}`,
    country,
    denomination: denom,
    year,
    canonical_thumb_url: thumb(id, 160, 160),
  }
}

// 30 reviews variés couvrant les cas typiques.
export const MOCK_QUEUE: ReviewItem[] = [
  {
    id: 'rev-001',
    crop_url: thumb('crop-be-2002-a', 480, 480),
    bbox: { x: 120, y: 80, w: 224, h: 224 },
    source: 'ebay',
    source_ref: 'ebay/195832104221',
    listing_title: '2 euros belgique 2002 albert II rare !!',
    listing_url: 'https://ebay.example/item/195832104221',
    listing_price: 4.5,
    candidates: [
      makeCandidate('BE', '2 EUR', 2002, 0.87),
      makeCandidate('BE', '2 EUR', 2008, 0.74),
      makeCandidate('NL', '2 EUR', 2002, 0.41),
      makeCandidate('LU', '2 EUR', 2002, 0.39),
      makeCandidate('FR', '2 EUR', 2002, 0.32),
    ],
    face_detected: 'obverse',
    priority: 30,
    is_multi_coin_lot: false,
    quality_score: 0.78,
    enqueued_at: '2026-04-26T10:14:02Z',
  },
  {
    id: 'rev-002',
    crop_url: thumb('crop-de-2020', 480, 480),
    bbox: null,
    source: 'catawiki',
    source_ref: 'catawiki/auction-9912',
    listing_title: 'Allemagne 2 € commémorative Brandebourg 2020',
    listing_url: null,
    listing_price: 12.0,
    candidates: [
      makeCandidate('DE', '2 EUR Brandebourg', 2020, 0.94),
      makeCandidate('DE', '2 EUR', 2020, 0.61),
      makeCandidate('DE', '2 EUR Saxe', 2020, 0.42),
      makeCandidate('DE', '2 EUR Bavière', 2020, 0.39),
      makeCandidate('AT', '2 EUR', 2020, 0.18),
    ],
    face_detected: 'reverse',
    priority: 20,
    is_multi_coin_lot: false,
    quality_score: 0.88,
    enqueued_at: '2026-04-26T11:02:18Z',
  },
  {
    id: 'rev-003',
    crop_url: thumb('crop-trash', 480, 480),
    bbox: null,
    source: 'ebay',
    source_ref: 'ebay/195999999111',
    listing_title: 'lot pieces euros - vrac voir photos',
    listing_url: 'https://ebay.example/item/195999999111',
    listing_price: null,
    candidates: [
      makeCandidate('FR', '1 EUR', 2010, 0.18),
      makeCandidate('IT', '1 EUR', null, 0.16),
      makeCandidate('BE', '50c', null, 0.14),
    ],
    face_detected: null,
    priority: 80,
    is_multi_coin_lot: true,
    quality_score: 0.21,
    enqueued_at: '2026-04-26T12:30:11Z',
  },
  {
    id: 'rev-004',
    crop_url: thumb('crop-fr-2019', 480, 480),
    bbox: { x: 60, y: 40, w: 280, h: 280 },
    source: 'mdp',
    source_ref: 'mdp/2019-mona-lisa',
    listing_title: 'Pièce de 2 € Léonard de Vinci 500e anniversaire',
    listing_url: null,
    listing_price: 28.5,
    candidates: [
      makeCandidate('FR', '2 EUR Léonard', 2019, 0.96),
      makeCandidate('IT', '2 EUR Léonard', 2019, 0.52),
      makeCandidate('FR', '2 EUR', 2019, 0.31),
      makeCandidate('FR', '2 EUR Mitterrand', 2016, 0.18),
      makeCandidate('FR', '2 EUR Rugby', 2023, 0.12),
    ],
    face_detected: 'reverse',
    priority: 10,
    is_multi_coin_lot: false,
    quality_score: 0.93,
    enqueued_at: '2026-04-26T13:45:50Z',
  },
  {
    id: 'rev-005',
    crop_url: thumb('crop-bad-meta', 480, 480),
    bbox: null,
    source: 'ebay',
    source_ref: 'ebay/195111222333',
    listing_title: 'piece rare ancienne collection',
    listing_url: 'https://ebay.example/item/195111222333',
    listing_price: 8.0,
    candidates: [
      makeCandidate('XX', '?', null, 0.22),
      makeCandidate('XX', '?', null, 0.19),
    ],
    face_detected: 'unknown',
    priority: 70,
    is_multi_coin_lot: false,
    quality_score: 0.45,
    enqueued_at: '2026-04-26T14:01:30Z',
  },
  // Ajout de 25 entrées plus variées (boucle pour densité)
  ...Array.from({ length: 25 }, (_, i): ReviewItem => {
    const idx = i + 6
    const countries = ['IT', 'ES', 'NL', 'PT', 'GR', 'AT', 'IE', 'FI', 'LU', 'SI']
    const country = countries[i % countries.length]
    const year = 2002 + (i % 24)
    const denoms = ['2 EUR', '1 EUR', '50c', '2 EUR commémo']
    const denom = denoms[i % denoms.length]
    const goodTop5 = i % 4 !== 3
    const isLot = i % 8 === 5
    return {
      id: `rev-${String(idx).padStart(3, '0')}`,
      crop_url: thumb(`crop-${country}-${year}-${i}`, 480, 480),
      bbox: i % 3 === 0 ? null : { x: 80 + (i % 5) * 12, y: 60 + (i % 4) * 10, w: 240, h: 240 },
      source: (['ebay', 'catawiki', 'mdp', 'lmdlp'] as ReviewSource[])[i % 4],
      source_ref: `${(['ebay', 'catawiki', 'mdp', 'lmdlp'] as ReviewSource[])[i % 4]}/${100000 + idx}`,
      listing_title:
        goodTop5
          ? `${COUNTRY_LABEL[country]} ${denom} ${year}${i % 5 === 0 ? ' SUP' : ''}`
          : `lot pieces - vrac collection`,
      listing_url: i % 2 === 0 ? `https://example/${idx}` : null,
      listing_price: i % 3 === 0 ? null : 3 + (i % 18),
      candidates: goodTop5
        ? [
            makeCandidate(country, denom, year, 0.7 + (i % 25) / 100),
            makeCandidate(country, denom, year + 1, 0.42),
            makeCandidate(country, denom, year - 1, 0.35),
            makeCandidate(country, denom, null, 0.22),
            makeCandidate(country, '1 EUR', year, 0.14),
          ]
        : [
            makeCandidate(country, denom, year, 0.25),
            makeCandidate(country, '1 EUR', year, 0.18),
          ],
      face_detected: (['obverse', 'reverse', 'unknown', null] as (ReviewFace | null)[])[i % 4],
      priority: 30 + (i % 60),
      is_multi_coin_lot: isLot,
      quality_score: 0.4 + (i % 50) / 100,
      enqueued_at: new Date(Date.parse('2026-04-26T08:00:00Z') + idx * 600 * 1000).toISOString(),
    }
  }),
]
